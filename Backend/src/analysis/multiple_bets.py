import logging
from ..core import config
from ..core.database import get_db_connection
from ..core.session_manager import get_active_session
from ..core.database_utils import retry_database_lock
from ..core.prisma_finance import get_prisma_bankroll, deduct_prisma_funds, update_prisma_bankroll

logger = logging.getLogger(__name__)

def generer_pari_multiple(journee, predictions_selectionnees, conn=None):
    """
    Crée un pari combiné à partir d'une sélection de prédictions.
    """
    if not config.ACTIVATE_MULTIPLE_BETS:
        return None

    if len(predictions_selectionnees) < 2:
        logger.info(f"Pas assez de prédictions ({len(predictions_selectionnees)}) pour un pari multiple.")
        return None

    # Limiter au nombre maximum configuré
    selection = predictions_selectionnees[:config.MAX_COMBINED_MATCHES]
    
    active_session = get_active_session()
    session_id = active_session['id']

    # Si une connexion est fournie, on l'utilise directement sans context manager
    if conn:
        return _generer_pari_internal(conn, journee, selection, session_id, active_session)
    
    # Sinon, on ouvre une nouvelle connexion (ancien comportement fallback)
    try:
        # Connexion marquée écriture car on insère pari_multiple + items
        with get_db_connection(write=True) as conn:
            return _generer_pari_internal(conn, journee, selection, session_id, active_session)
    except Exception as e:
        logger.error(f"Erreur lors de la génération du pari multiple : {e}", exc_info=True)
        import traceback; traceback.print_exc()
        return None

def _generer_pari_internal(conn, journee, selection, session_id, active_session):
    try:
        cursor = conn.cursor()

        # 1. Calculer la cote totale
        cote_totale = 1.0
        prediction_ids = []
        
        for p in selection:
            # Récupérer la cote jouée pour ce match
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
                prediction_ids.append(p.get('id') or p.get('prediction_id')) # Dépend de comment c'est passé
            else:
                logger.warning(f"Cote introuvable pour le match {p['match_id']}, prédiction {p['prediction']}")
                print(f"DEBUG: Cote introuvable pour match: {p['match_id']}")
                return None

        if not prediction_ids:
            return None

        # 2. Déterminer la mise et vérifier les fonds PRISMA
        prisma_bankroll = get_prisma_bankroll()
        
        # Utiliser montant fixe ou pourcentage selon configuration
        if config.USE_MONTANT_FIXE:
            mise_ar = config.MONTANT_FIXE_MULTIPLE
        else:
            mise_ar = int(prisma_bankroll * config.PERCENTAGE_BANKROLL_MULTIPLE)

        if mise_ar < 500: # Mise minimum arbitraire
            logger.info(f"Mise trop faible ({mise_ar} Ar) pour pari multiple.")
            print(f"DEBUG: mise_ar too low: {mise_ar}, prisma_bankroll: {prisma_bankroll}")
            return None
        
        # Empêcher une mise supérieure au bankroll disponible
        if mise_ar > prisma_bankroll:
            logger.warning(f"Mise {mise_ar} Ar supérieure au bankroll PRISMA ({prisma_bankroll} Ar), pari multiple annulé.")
            return None

        # Vérifier et déduire les fonds PRISMA
        fonds_suffisants, nouveau_bankroll = deduct_prisma_funds(mise_ar)
        if not fonds_suffisants:
            logger.warning(f"Fonds PRISMA insuffisants: {prisma_bankroll} Ar < {mise_ar} Ar")
            return None

        # 3. Enregistrer le pari multiple
        cursor.execute("""
            INSERT INTO pari_multiple (session_id, journee, mise_ar, cote_totale)
            VALUES (?, ?, ?, ?)
        """, (session_id, journee, mise_ar, cote_totale))
        pari_id = cursor.lastrowid

        # 4. Enregistrer les items
        for pred_id in prediction_ids:
            # Si pred_id est None (pas encore en DB), on doit le récupérer ou s'assurer qu'il existe
            if pred_id is None:
                # On cherche l'ID de la prédiction qu'on vient d'insérer dans intelligence.py
                # Note: Idéalement, intelligence.py nous passe les IDs retournés par cursor.lastrowid
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
    """
    Vérifie les résultats des paris combinés en attente.
    Optimisée pour réduire la durée des transactions.
    """
    active_session = get_active_session(conn=conn)
    session_id = active_session['id']

    if conn:
        return _valider_paris_multiples_internal(conn, session_id)
        
    try:
        # On autorise l'écriture pour ajuster le score PRISMA lors de la validation.
        with get_db_connection(write=True) as new_conn:
            return _valider_paris_multiples_internal(new_conn, session_id)
    except Exception as e:
        logger.error(f"Erreur lors de la validation des paris multiples : {e}", exc_info=True)

def _valider_paris_multiples_internal(conn, session_id):
    cursor = conn.cursor()

    # Récupérer les paris en attente avec leurs données
    cursor.execute("""
        SELECT id, mise_ar, cote_totale FROM pari_multiple 
        WHERE session_id = ? AND resultat IS NULL
    """, (session_id,))
    paris_en_attente = cursor.fetchall()

    if not paris_en_attente:
        return

    # Préparer le bankroll PRISMA une seule fois
    prisma_bankroll = get_prisma_bankroll()

    # Traiter chaque pari
    for pari in paris_en_attente:
        pari_id, mise, cote = pari
        
        # Vérifier si toutes les prédictions liées sont terminées
        cursor.execute("""
            SELECT p.succes 
            FROM pari_multiple_items pmi
            JOIN predictions p ON pmi.prediction_id = p.id
            WHERE pmi.pari_multiple_id = ?
        """, (pari_id,))
        resultats = cursor.fetchall()
        
        if not resultats or any(r[0] is None for r in resultats):
            continue  # Pas encore tous les résultats
        
        # Calculer le résultat
        tout_gagne = all(r[0] == 1 for r in resultats)
        resultat = 1 if tout_gagne else 0
        profit_net = int(mise * cote) - mise if tout_gagne else -mise
        nouveau_bankroll = prisma_bankroll + profit_net

        # Mise à jour du portefeuille JSON
        update_prisma_bankroll(session_id, nouveau_bankroll, mise, resultat, cote)
        prisma_bankroll = nouveau_bankroll  # Mettre à jour pour le prochain pari

        # Calcul du score PRISMA pour ce pari
        delta_score = config.PRISMA_POINTS_VICTOIRE if tout_gagne else config.PRISMA_POINTS_DEFAITE
        
        # Mise à jour de la table pari_multiple
        cursor.execute("""
            UPDATE pari_multiple 
            SET resultat = ?, profit_net = ?, bankroll_apres = ?
            WHERE id = ?
        """, (resultat, profit_net, nouveau_bankroll, pari_id))

        # Mise à jour du score dans la session active
        cursor.execute(
            "UPDATE sessions SET score_prisma = score_prisma + ? WHERE id = ?",
            (delta_score, session_id)
        )
        
        logger.info(
            f"Pari Multiple {pari_id} validé : {'GAGNE' if tout_gagne else 'PERDU'} "
            f"(Profit: {profit_net} Ar, Bankroll PRISMA: {nouveau_bankroll} Ar, "
            f"Delta score PRISMA: {delta_score})"
        )
