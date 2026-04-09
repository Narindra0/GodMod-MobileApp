import logging

from ..core import config
from ..core.database import get_db_connection
from ..core.prisma_finance import (
    deduct_prisma_funds,
    get_prisma_bankroll,
    is_prisma_stop_loss_active,
    update_prisma_bankroll,
)
from ..core import zeus_finance
from ..core.session_manager import get_active_session

logger = logging.getLogger(__name__)


def generer_pari_multiple(journee, predictions_selectionnees, strategie='PRISMA', conn=None):
    if not config.ACTIVATE_MULTIPLE_BETS:
        return None
    
    # Contrainte ZEUS: Exactement 2 matchs
    if strategie == 'ZEUS':
        if len(predictions_selectionnees) != 2:
            logger.info(f"ZEUS nécessite exactement 2 prédictions pour un combiné (actuel: {len(predictions_selectionnees)}).")
            return None
        selection = predictions_selectionnees
    else:
        # PRISMA (comportement historique)
        if len(predictions_selectionnees) < 2:
            logger.info(f"Pas assez de prédictions ({len(predictions_selectionnees)}) pour un pari multiple PRISMA.")
            return None
        selection = predictions_selectionnees[: config.MAX_COMBINED_MATCHES]
        
    active_session = get_active_session(conn=conn)
    session_id = active_session["id"]
    
    if conn:
        return _generer_pari_internal(conn, journee, selection, session_id, active_session, strategie)
    try:
        with get_db_connection(write=True) as conn:
            return _generer_pari_internal(conn, journee, selection, session_id, active_session, strategie)
    except Exception as e:
        logger.error(f"Erreur lors de la génération du pari multiple ({strategie}) : {e}", exc_info=True)
        return None


def _generer_pari_internal(conn, journee, selection, session_id, active_session, strategie):
    # Vérification Stop-Loss selon stratégie
    if strategie == 'PRISMA' and is_prisma_stop_loss_active():
        logger.warning(f"[STOP-LOSS] Bankroll PRISMA sous le seuil. Pari multiple refusé.")
        return None
    elif strategie == 'ZEUS' and zeus_finance.is_zeus_stop_loss_active(conn=conn):
        logger.warning(f"[STOP-LOSS] Bankroll ZEUS sous le seuil. Pari multiple refusé.")
        return None

    try:
        cursor = conn.cursor()
        cote_totale = 1.0
        prediction_ids = []
        for p in selection:
            cursor.execute(
                """
                SELECT
                    CASE
                        WHEN %s = '1' THEN cote_1
                        WHEN %s IN ('X', 'N') THEN cote_x
                        WHEN %s = '2' THEN cote_2
                    END AS case
                FROM matches WHERE id = %s
            """,
                (p["prediction"], p["prediction"], p["prediction"], p["match_id"]),
            )
            row = cursor.fetchone()
            if row and row["case"]:
                cote_totale *= float(row["case"])
                prediction_ids.append(p.get("id") or p.get("prediction_id"))
            else:
                logger.warning(f"Cote introuvable pour le match {p['match_id']}, prédiction {p['prediction']}")
                return None
        
        if not prediction_ids:
            return None

        # Gestion de la mise selon stratégie
        if strategie == 'PRISMA':
            bankroll = get_prisma_bankroll()
            mise_ar = config.MONTANT_FIXE_MULTIPLE if config.USE_MONTANT_FIXE else int(bankroll * config.PERCENTAGE_BANKROLL_MULTIPLE)
            if mise_ar < 500: return None
            f_ok, nouveau_bankroll = deduct_prisma_funds(mise_ar)
            if not f_ok: return None
        else: # ZEUS
            bankroll = zeus_finance.get_zeus_bankroll(conn=conn)
            mise_ar = config.MONTANT_FIXE_MULTIPLE # Par défaut pour ZEUS combiné
            if bankroll < mise_ar:
                logger.warning(f"Fonds ZEUS insuffisants : {bankroll} Ar < {mise_ar} Ar")
                return None
            nouveau_bankroll = bankroll - mise_ar
            # Enregistrement du mouvement bankroll pour ZEUS
            zeus_finance.record_zeus_combined_bet(session_id, journee, mise_ar, nouveau_bankroll, conn)

        cursor.execute(
            """
            INSERT INTO pari_multiple (session_id, journee, mise_ar, cote_totale, strategie)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """,
            (session_id, journee, mise_ar, cote_totale, strategie),
        )
        pari_id = cursor.fetchone()["id"]
        
        for pred_id in prediction_ids:
            if pred_id:
                cursor.execute(
                    "INSERT INTO pari_multiple_items (pari_multiple_id, prediction_id) VALUES (%s, %s)",
                    (pari_id, pred_id),
                )
        
        logger.info(f"Pari multiple {strategie} créé (ID: {pari_id}) | Cote: {cote_totale:.2f} | Mise: {mise_ar} Ar")
        return {"id": pari_id, "cote_totale": cote_totale, "mise_ar": mise_ar, "nb_matchs": len(prediction_ids)}
    except Exception as e:
        logger.error(f"Erreur génération combiné {strategie}: {e}", exc_info=True)
        return None


def valider_paris_multiples(conn=None):
    active_session = get_active_session(conn=conn)
    session_id = active_session["id"]
    if conn:
        return _valider_paris_multiples_internal(conn, session_id)
    try:
        with get_db_connection(write=True) as new_conn:
            return _valider_paris_multiples_internal(new_conn, session_id)
    except Exception as e:
        logger.error(f"Erreur lors de la validation des paris multiples : {e}", exc_info=True)


def _valider_paris_multiples_internal(conn, session_id):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, mise_ar, cote_totale, strategie FROM pari_multiple WHERE session_id = %s AND resultat IS NULL",
        (session_id,),
    )
    paris_en_attente = cursor.fetchall()
    if not paris_en_attente:
        return

    for pari in paris_en_attente:
        pari_id, mise, cote, strat = pari["id"], pari["mise_ar"], pari["cote_totale"], pari["strategie"]
        
        # Récupération du bankroll actuel selon stratégie
        if strat == 'PRISMA':
            bankroll = get_prisma_bankroll()
        else: # ZEUS
            bankroll = zeus_finance.get_zeus_bankroll(conn=conn)

        cursor.execute(
            """
            SELECT p.succes FROM pari_multiple_items pmi
            JOIN predictions p ON pmi.prediction_id = p.id
            WHERE pmi.pari_multiple_id = %s
        """,
            (pari_id,),
        )
        resultats = cursor.fetchall()
        if not resultats or any(r["succes"] is None for r in resultats):
            continue
            
        tout_gagne = all(r["succes"] == 1 for r in resultats)
        resultat = 1 if tout_gagne else 0
        
        if tout_gagne:
            profit_net = int(mise * (cote - 1))
            nouveau_bankroll = bankroll + int(mise * cote)
        else:
            profit_net = -mise
            nouveau_bankroll = bankroll # Déjà déduit à la création
        
        if strat == 'PRISMA':
            # Fix: Mise à jour du bankroll PRISMA directement dans la même transaction
            # (update_prisma_bankroll ouvrait une 2e connexion → risque de deadlock)
            cursor.execute(
                "INSERT INTO prisma_config (key, value_int, last_update) "
                "VALUES ('bankroll_prisma', %s, CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int, last_update = CURRENT_TIMESTAMP",
                (int(nouveau_bankroll),)
            )
            delta_score = config.PRISMA_POINTS_VICTOIRE if tout_gagne else config.PRISMA_POINTS_DEFAITE
            cursor.execute("UPDATE sessions SET score_prisma = score_prisma + %s WHERE id = %s", (delta_score, session_id))
        else: # ZEUS
            # Mise à jour du bankroll ZEUS dans la même transaction
            cursor.execute(
                "INSERT INTO prisma_config (key, value_int, last_update) "
                "VALUES ('bankroll_zeus', %s, CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int, last_update = CURRENT_TIMESTAMP",
                (int(nouveau_bankroll),)
            )
            # Log final result in historique_paris
            from ..zeus.database.queries import PariRecord, enregistrer_pari
            enregistrer_pari(PariRecord(
                session_id=session_id, prediction_id=None, journee=0, type_pari='COMBINED_RESULT',
                mise_ar=0, pourcentage_bankroll=0, cote_jouee=float(cote),
                resultat=resultat, profit_net=profit_net, bankroll_apres=nouveau_bankroll,
                probabilite_implicite=None, action_id=0, strategie='ZEUS'
            ), conn)
            delta_score = 3 if tout_gagne else -3
            cursor.execute("UPDATE sessions SET score_zeus = score_zeus + %s WHERE id = %s", (delta_score, session_id))

        cursor.execute(
            "UPDATE pari_multiple SET resultat = %s, profit_net = %s, bankroll_apres = %s WHERE id = %s",
            (resultat, profit_net, nouveau_bankroll, pari_id),
        )
        logger.info(f"Pari Multiple {strat} {pari_id} validé : {'GAGNE' if tout_gagne else 'PERDU'}")
