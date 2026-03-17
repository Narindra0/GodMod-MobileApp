import logging
from ..core import config
from ..core.database import get_db_connection
from ..core.session_manager import get_active_session
from ..core.prisma_finance import get_prisma_bankroll, deduct_prisma_funds, update_prisma_bankroll, is_prisma_stop_loss_active
logger = logging.getLogger(__name__)
def generer_pari_multiple(journee, predictions_selectionnees, conn=None):
    if not config.ACTIVATE_MULTIPLE_BETS:
        return None
    if len(predictions_selectionnees) < 2:
        logger.info(f"Pas assez de prédictions ({len(predictions_selectionnees)}) pour un pari multiple.")
        return None
    selection = predictions_selectionnees[:config.MAX_COMBINED_MATCHES]
    active_session = get_active_session()
    session_id = active_session['id']
    if conn:
        return _generer_pari_internal(conn, journee, selection, session_id, active_session)
    try:
        with get_db_connection(write=True) as conn:
            return _generer_pari_internal(conn, journee, selection, session_id, active_session)
    except Exception as e:
        logger.error(f"Erreur lors de la génération du pari multiple : {e}", exc_info=True)
        import traceback; traceback.print_exc()
        return None
def _generer_pari_internal(conn, journee, selection, session_id, active_session):
    if is_prisma_stop_loss_active():
        logger.warning(f"[STOP-LOSS] Bankroll PRISMA sous le seuil. Pari multiple refusé.")
        return None
    try:
        cursor = conn.cursor()
        cote_totale = 1.0
        prediction_ids = []
        for p in selection:
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN ? = '1' THEN cote_1
                        WHEN ? = 'X' THEN cote_x
                        WHEN ? = '2' THEN cote_2
                    END
                FROM matches WHERE id = ?
            """, (p['prediction'], p['prediction'], p['prediction'], p['match_id']))
            row = cursor.fetchone()
            if row and row[0]:
                cote_totale *= float(row[0])
                prediction_ids.append(p.get('id') or p.get('prediction_id')) 
            else:
                logger.warning(f"Cote introuvable pour le match {p['match_id']}, prédiction {p['prediction']}")
                return None
        if not prediction_ids:
            return None
        prisma_bankroll = get_prisma_bankroll()
        if config.USE_MONTANT_FIXE:
            mise_ar = config.MONTANT_FIXE_MULTIPLE
        else:
            mise_ar = int(prisma_bankroll * config.PERCENTAGE_BANKROLL_MULTIPLE)
        if mise_ar < 500: 
            logger.info(f"Mise trop faible ({mise_ar} Ar) pour pari multiple.")
            return None
        if mise_ar > prisma_bankroll:
            logger.warning(f"Mise {mise_ar} Ar supérieure au bankroll PRISMA ({prisma_bankroll} Ar), pari multiple annulé.")
            return None
        fonds_suffisants, nouveau_bankroll = deduct_prisma_funds(mise_ar)
        if not fonds_suffisants:
            logger.warning(f"Fonds PRISMA insuffisants: {prisma_bankroll} Ar < {mise_ar} Ar")
            return None
        cursor.execute("""
            INSERT INTO pari_multiple (session_id, journee, mise_ar, cote_totale)
            VALUES (?, ?, ?, ?)
        """, (session_id, journee, mise_ar, cote_totale))
        pari_id = cursor.lastrowid
        for pred_id in prediction_ids:
            if pred_id is None:
                continue
            cursor.execute("""
                INSERT INTO pari_multiple_items (pari_multiple_id, prediction_id)
                VALUES (?, ?)
            """, (pari_id, pred_id))
        logger.info(f"Pari multiple créé (ID: {pari_id}) : {len(prediction_ids)} matchs, Cote: {cote_totale:.2f}, Mise: {mise_ar} Ar")
        return {
            'id': pari_id,
            'cote_totale': cote_totale,
            'mise_ar': mise_ar,
            'nb_matchs': len(prediction_ids)
        }
    except Exception as e:
        logger.error(f"Erreur lors de la génération du pari multiple : {e}", exc_info=True)
        import traceback; traceback.print_exc()
        return None
def valider_paris_multiples(conn=None):
    active_session = get_active_session(conn=conn)
    session_id = active_session['id']
    if conn:
        return _valider_paris_multiples_internal(conn, session_id)
    try:
        with get_db_connection(write=True) as new_conn:
            return _valider_paris_multiples_internal(new_conn, session_id)
    except Exception as e:
        logger.error(f"Erreur lors de la validation des paris multiples : {e}", exc_info=True)
def _valider_paris_multiples_internal(conn, session_id):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, mise_ar, cote_totale FROM pari_multiple 
        WHERE session_id = ? AND resultat IS NULL
    """, (session_id,))
    paris_en_attente = cursor.fetchall()
    if not paris_en_attente:
        return
    prisma_bankroll = get_prisma_bankroll()
    for pari in paris_en_attente:
        pari_id, mise, cote = pari
        cursor.execute("""
            SELECT p.succes 
            FROM pari_multiple_items pmi
            JOIN predictions p ON pmi.prediction_id = p.id
            WHERE pmi.pari_multiple_id = ?
        """, (pari_id,))
        resultats = cursor.fetchall()
        if not resultats or any(r[0] is None for r in resultats):
            continue  
        tout_gagne = all(r[0] == 1 for r in resultats)
        resultat = 1 if tout_gagne else 0
        profit_net = int(mise * (cote - 1)) if tout_gagne else -mise
        nouveau_bankroll = prisma_bankroll + profit_net
        update_prisma_bankroll(session_id, nouveau_bankroll, mise, resultat, cote)
        prisma_bankroll = nouveau_bankroll  
        delta_score = config.PRISMA_POINTS_VICTOIRE if tout_gagne else config.PRISMA_POINTS_DEFAITE
        cursor.execute("""
            UPDATE pari_multiple 
            SET resultat = ?, profit_net = ?, bankroll_apres = ?
            WHERE id = ?
        """, (resultat, profit_net, nouveau_bankroll, pari_id))
        cursor.execute(
            "UPDATE sessions SET score_prisma = score_prisma + ? WHERE id = ?",
            (delta_score, session_id)
        )
        logger.info(
            f"Pari Multiple {pari_id} validé : {'GAGNE' if tout_gagne else 'PERDU'} "
            f"(Profit: {profit_net} Ar, Bankroll PRISMA: {nouveau_bankroll} Ar, "
            f"Delta score PRISMA: {delta_score})"
        )
