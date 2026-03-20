import logging
from typing import List, Dict
import importlib
import sys
import functools
from ..core import config
from ..core.database import get_db_connection
from ..core.session_manager import get_active_session
from ..prisma import engine as prisma_engine
from ..prisma import selection as prisma_selection
from ..zeus.models.inference import get_zeus_model, predire_pari_zeus, formater_decision_zeus
from ..zeus.database.queries import get_matches_for_journee, enregistrer_pari, valider_paris_zeus
from . import multiple_bets
from . import ai_booster
from ..core.console import console, print_verbose
from ..core.prisma_finance import is_prisma_stop_loss_active

logger = logging.getLogger(__name__)

# Cache pour les sessions et calculs statiques par journee
@functools.lru_cache(maxsize=32)
def get_cached_active_session():
    return get_active_session()

def vider_cache_intelligence():
    """Vide tous les caches de ce module (H2H, session, etc.)"""
    get_cached_active_session.cache_clear()
    analyser_confrontations_directes_cached.cache_clear()
    logger.info("Cache intelligence vidé pour synchronisation.")
def _reload_config():
    if 'src.core.config' in sys.modules:
        importlib.reload(sys.modules['src.core.config'])
        globals()['config'] = sys.modules['src.core.config']
def calculer_probabilite_avec_fallback(equipe_dom_id, equipe_ext_id, cote_1=None, cote_x=None, cote_2=None):
    if cote_1 is not None and cote_x is not None and cote_2 is not None:
        return calculer_probabilite_amelioree(equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2)
    else:
        logger.warning(f"Cotes manquantes pour match {equipe_dom_id} vs {equipe_ext_id}. Utilisation du calcul simple.")
        return calculer_probabilite(equipe_dom_id, equipe_ext_id)
def calculer_probabilite(equipe_dom_id, equipe_ext_id, conn=None):
    if conn:
        active_session = get_active_session(conn=conn)
    else:
        active_session = get_cached_active_session()
    
    session_id = active_session['id']
    if conn:
        return _calculer_probabilite_internal(conn, session_id, equipe_dom_id, equipe_ext_id)
    try:
        with get_db_connection() as conn:
            return _calculer_probabilite_internal(conn, session_id, equipe_dom_id, equipe_ext_id)
    except Exception as e:
        logger.error(f"Erreur lors du calcul de probabilité : {e}", exc_info=True)
        return None, 0
def _calculer_probabilite_internal(conn, session_id, equipe_dom_id, equipe_ext_id):
    cursor = conn.cursor()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = %s AND equipe_id = %s ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
    stats_dom = cursor.fetchone()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = %s AND equipe_id = %s ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
    stats_ext = cursor.fetchone()
    if not stats_dom or not stats_ext:
        return None, 0
    pts_dom, forme_dom = stats_dom['points'], stats_dom['forme']
    pts_ext, forme_ext = stats_ext['points'], stats_ext['forme']
    score_pts = (pts_dom - pts_ext) * 0.5
    def pondere_forme(f):
        valeurs = {'V': 3, 'N': 1, 'D': 0}
        return sum(valeurs.get(c, 0) for c in (f[-5:] if f else "")) 
    score_forme = pondere_forme(forme_dom) - pondere_forme(forme_ext)
    score_total = score_pts + score_forme
    if score_total > 5:
        return "1", score_total
    elif score_total < -5:
        return "2", abs(score_total)
    else:
        return "X", abs(score_total)
def calculer_probabilite_amelioree(equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2, conn=None):
    if conn:
        active_session = get_active_session(conn=conn)
    else:
        active_session = get_cached_active_session()
    
    session_id = active_session['id']
    if conn:
        return _calculer_probabilite_amelioree_internal(conn, session_id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2)
    try:
        with get_db_connection() as conn:
            return _calculer_probabilite_amelioree_internal(conn, session_id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2)
    except Exception as e:
        logger.error(f"Erreur lors du calcul PRISMA : {e}", exc_info=True)
        return None, 0
def _calculer_probabilite_amelioree_internal(conn, session_id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2):
    cursor = conn.cursor()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = %s AND equipe_id = %s ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
    stats_dom = cursor.fetchone()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = %s AND equipe_id = %s ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
    stats_ext = cursor.fetchone()
    if not stats_dom or not stats_ext:
        return None, 0
    pts_dom, forme_dom = stats_dom['points'], stats_dom['forme']
    pts_ext, forme_ext = stats_ext['points'], stats_ext['forme']
    buts_dom = analyser_buts_recents_internal(cursor, session_id, equipe_id=equipe_dom_id)
    buts_ext = analyser_buts_recents_internal(cursor, session_id, equipe_id=equipe_ext_id)
    bonus_h2h = analyser_confrontations_directes(equipe_dom_id, equipe_ext_id, conn=conn)
    prisma_data = {
        'pts_dom': pts_dom, 'pts_ext': pts_ext,
        'forme_dom': forme_dom, 'forme_ext': forme_ext,
        'cote_1': cote_1, 'cote_x': cote_x, 'cote_2': cote_2,
        'bonus_h2h': bonus_h2h
    }
    if buts_dom and buts_ext:
        prisma_data.update({
            'bp_dom': buts_dom[0], 'bc_dom': buts_dom[1],
            'bp_ext': buts_ext[0], 'bc_ext': buts_ext[1]
        })
    prediction, score = prisma_engine.calculer_score_prisma(prisma_data)
    if prediction is None:
        return None, 0
    return prediction, score
def analyser_performances_recentes(conn=None):
    active_session = get_active_session(conn=conn)
    session_id = active_session['id']
    if conn:
        return _analyser_performances_recentes_internal(conn, session_id)
    try:
        with get_db_connection() as conn:
            return _analyser_performances_recentes_internal(conn, session_id)
    except Exception as e:
        logger.error(f"Erreur DB performances : {e}")
        return 1.0, "Erreur"
def _analyser_performances_recentes_internal(conn, session_id):
    cursor = conn.cursor()
    cursor.execute("SELECT succes FROM predictions WHERE session_id = %s AND succes IS NOT NULL ORDER BY id DESC LIMIT 15", (session_id,))
    resultats = cursor.fetchall()
    if not resultats: return 1.0, "Neutre"
    succes_count = sum(1 for r in resultats if r['succes'] == 1)
    return succes_count / len(resultats), f"{succes_count}/{len(resultats)}"
def selectionner_meilleurs_matchs(journee, conn=None):
    _reload_config()
    active_session = get_active_session(conn=conn)
    session_id = active_session['id']
    if conn:
        return _selectionner_meilleurs_matchs_internal(conn, session_id, journee)
    try:
        with get_db_connection() as conn:
            return _selectionner_meilleurs_matchs_internal(conn, session_id, journee)
    except Exception as e:
        logger.error(f"Erreur sélection standard : {e}")
        return []
def _selectionner_meilleurs_matchs_internal(conn, session_id, journee):
    cursor = conn.cursor()
    cursor.execute("SELECT id, equipe_dom_id, equipe_ext_id FROM matches WHERE session_id = %s AND journee = %s", (session_id, journee))
    matchs = cursor.fetchall()
    predictions = []
    for m in matchs:
        match_id, dom_id, ext_id = m['id'], m['equipe_dom_id'], m['equipe_ext_id']
        pred, conf = calculer_probabilite(dom_id, ext_id, conn=conn)
        if pred:
            predictions.append({
                'match_id': match_id,
                'prediction': pred,
                'fiabilite': conf
            })
    for p in predictions:
        cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source) VALUES (%s, %s, %s, %s, %s)",
                     (session_id, p['match_id'], p['prediction'], p['fiabilite'], 'PRISMA'))
    return predictions
def selectionner_meilleurs_matchs_ameliore(journee, conn=None):
    _reload_config()
    if getattr(config, 'ZEUS_DEEP_SLEEP', False):
        print_verbose(f"💤 [IA] Sommeil Profond actif (Entraînement ZEUS). Aucune prédiction.")
        return []
    if journee < 4:
        print_verbose(f"Info : Journée {journee} < 4. Pas assez de données.")
        return []
    active_session = get_active_session(conn=conn)
    session_id = active_session['id']
    if conn:
        return _selectionner_meilleurs_matchs_ameliore_internal(conn, session_id, journee)
    try:
        with get_db_connection(write=True) as conn:
            return _selectionner_meilleurs_matchs_ameliore_internal(conn, session_id, journee)
    except Exception as e:
        logger.error(f"Erreur sélection PRISMA : {e}", exc_info=True)
        return []
def _selectionner_meilleurs_matchs_ameliore_internal(conn, session_id, journee):
    if is_prisma_stop_loss_active():
        print_verbose(f"   ⛔ [STOP-LOSS] Bankroll PRISMA sous {config.BANKROLL_STOP_LOSS} Ar. Aucune prédiction PRISMA générée.")
        logger.warning(f"[STOP-LOSS] Bankroll PRISMA sous seuil. Paris PRISMA suspendus.")
        return []
    cursor = conn.cursor()
    taux_succes, _ = analyser_performances_recentes(conn=conn)
    seuil_confiance, mode_descr = prisma_selection.determiner_seuil_dynamique(taux_succes)
    print_verbose(f"   [PRISMA] Mode {mode_descr} | Seuil: {seuil_confiance}")
    cursor.execute("SELECT id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2 FROM matches WHERE session_id = %s AND journee = %s", (session_id, journee))
    matchs = cursor.fetchall()
    cursor.execute("SELECT id, nom FROM equipes")
    equipes_noms = {r['id']: r['nom'] for r in cursor.fetchall()}
    # --- Vérification globale AI Enabled (Une seule fois hors de la boucle) ---
    cursor.execute("SELECT value_int FROM prisma_config WHERE key = 'ai_enabled'")
    row_ai = cursor.fetchone()
    ai_enabled = bool(row_ai['value_int']) if row_ai and row_ai['value_int'] is not None else True

    raw_predictions = []
    for m in matchs:
        match_id, dom_id, ext_id, c1, cx, c2 = m['id'], m['equipe_dom_id'], m['equipe_ext_id'], m['cote_1'], m['cote_x'], m['cote_2']
        pred, conf = calculer_probabilite_amelioree(dom_id, ext_id, c1, cx, c2, conn=conn)
        if pred:
            if ai_enabled:
                # --- Lecture du cache Gemini (lecture seule, aucun appel API) ---
                gemini_boost = ai_booster.get_cached_boost(session_id, journee, dom_id, ext_id, conn)
                conf_final = float(conf) + gemini_boost
                if gemini_boost != 0.0:
                    print_verbose(f"   [IA] {equipes_noms.get(dom_id)} vs {equipes_noms.get(ext_id)} → Boost {gemini_boost:+.1f} | Score: {conf_final:.2f}")
            else:
                gemini_boost = 0.0
                conf_final = float(conf)
                print_verbose(f"   [PRISMA PUR] {equipes_noms.get(dom_id)} vs {equipes_noms.get(ext_id)} → IA désactivée | Score: {conf_final:.2f}")

            if conf_final >= seuil_confiance:
                raw_predictions.append({
                    'match_id': match_id, 'equipe_dom_id': dom_id, 'equipe_ext_id': ext_id,
                    'equipe_dom': equipes_noms.get(dom_id), 'equipe_ext': equipes_noms.get(ext_id),
                    'prediction': pred, 'confiance': conf_final, 'fiabilite': conf_final,
                    'boost_ia': gemini_boost, 'score_base': float(conf),
                    'cote_1': c1, 'cote_x': cx, 'cote_2': c2
                })
    final_selection = prisma_selection.filtrer_meilleurs_matchs(raw_predictions, config.MAX_PREDICTIONS_PAR_JOURNEE)
    
    from src.core.prisma_finance import deduct_prisma_funds, get_prisma_bankroll

    for p in final_selection:
        # 1. Insert into predictions
        cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                     (session_id, p['match_id'], p['prediction'], p['fiabilite'], 'PRISMA'))
        pred_id = cursor.fetchone()['id']
        p['id'] = pred_id

        # 2. Place Simple Bet for PRISMA
        # We use a default stake of 1000 Ar or PERCENTAGE if not fixed
        mise_ar = config.MONTANT_FIXE_MULTIPLE if config.USE_MONTANT_FIXE else int(get_prisma_bankroll() * 0.05)
        
        fonds_suffisants, current_bankroll = deduct_prisma_funds(mise_ar)
        if fonds_suffisants:
            cote_val = p.get('cote_1') if p['prediction'] == '1' else (p.get('cote_x') if p['prediction'] == 'X' else p.get('cote_2'))
            enregistrer_pari(
                session_id=session_id,
                prediction_id=pred_id,
                journee=journee,
                type_pari=p['prediction'],
                mise_ar=mise_ar,
                pourcentage_bankroll=0.05,
                cote_jouee=float(cote_val) if cote_val else 0,
                resultat=None,
                profit_net=None,
                bankroll_apres=current_bankroll,
                probabilite_implicite=1.0 / float(cote_val) if cote_val else None,
                action_id=0,
                conn=conn,
                strategie='PRISMA'
            )
    
    multiple_bets.generer_pari_multiple(journee, final_selection, conn=conn)
    return final_selection
def analyser_buts_recents_internal(cursor, session_id, equipe_id):
    try:
        cursor.execute("""
            SELECT 
                CASE WHEN equipe_dom_id = %s THEN score_dom ELSE score_ext END as buts_pour,
                CASE WHEN equipe_dom_id = %s THEN score_ext ELSE score_dom END as buts_contre
            FROM matches 
            WHERE session_id = %s AND (equipe_dom_id = %s OR equipe_ext_id = %s) AND score_dom IS NOT NULL
            ORDER BY journee DESC LIMIT 5
        """, (equipe_id, equipe_id, session_id, equipe_id, equipe_id))
        res = cursor.fetchall()
        if not res: return None
        return sum(r['buts_pour'] for r in res), sum(r['buts_contre'] for r in res)
    except: return None
@functools.lru_cache(maxsize=128)
def analyser_confrontations_directes_cached(session_id, equipe_dom_id, equipe_ext_id):
    try:
        with get_db_connection() as conn:
            return _analyser_confrontations_directes_internal(conn, session_id, equipe_dom_id, equipe_ext_id)
    except: return 0

def analyser_confrontations_directes(equipe_dom_id, equipe_ext_id, conn=None):
    if conn:
        active_session = get_active_session(conn=conn)
    else:
        active_session = get_cached_active_session()
    
    session_id = active_session['id']
    if conn:
        return _analyser_confrontations_directes_internal(conn, session_id, equipe_dom_id, equipe_ext_id)
    return analyser_confrontations_directes_cached(session_id, equipe_dom_id, equipe_ext_id)
def _analyser_confrontations_directes_internal(conn, session_id, equipe_dom_id, equipe_ext_id):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT score_dom, score_ext FROM matches 
        WHERE session_id = %s AND equipe_dom_id = %s AND equipe_ext_id = %s AND score_dom IS NOT NULL
        ORDER BY journee DESC LIMIT 5
    """, (session_id, equipe_dom_id, equipe_ext_id))
    hist = cursor.fetchall()
    if not hist or len(hist) < 3: return 0
    v_dom = sum(1 for h in hist if h['score_dom'] > h['score_ext'])
    nuls = sum(1 for h in hist if h['score_dom'] == h['score_ext'])
    t_vic = v_dom / len(hist)
    if t_vic >= 0.80: return 3.0
    if t_vic >= 0.60: return 1.5
    if (nuls / len(hist)) >= 0.60: return -2.0
    if t_vic <= 0.20: return -3.0
    return 0
def obtenir_predictions_zeus_journee(journee: int) -> List[Dict]:
    _reload_config()
    if getattr(config, 'ZEUS_DEEP_SLEEP', False):
        return []
    model = get_zeus_model()
    if not model:
        logger.warning("Modèle ZEUS non trouvé pour l'inférence.")
        return []
    active_session = get_active_session()
    session_id = active_session['id']
    predictions = []
    try:
        with get_db_connection() as conn:
            matches = get_matches_for_journee(journee, conn)
            cursor = conn.cursor()
            # Récupérer capital actuel et dette
            cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = %s AND strategie = 'ZEUS' ORDER BY id_pari DESC LIMIT 1", (session_id,))
            row = cursor.fetchone()
            capital_actuel = row['bankroll_apres'] if row else active_session['capital_initial']
            
            cursor.execute("SELECT dette_zeus, stop_loss_override FROM sessions WHERE id = %s", (session_id,))
            sess_row = cursor.fetchone()
            dette_actuelle = sess_row['dette_zeus'] if sess_row else 0
            override_stop_loss = sess_row['stop_loss_override'] if sess_row else False
            
            # Limite de paris par jour pour éviter la sur-exposition
            limite_journaliere = 1 if dette_actuelle > 0 else 3
            paris_engages = 0

            model = get_zeus_model()
            if model:
                for m in matches:
                    if paris_engages >= limite_journaliere:
                        print_verbose(f"   🛑 [LIMITE ZEUS] Limite de {limite_journaliere} paris atteinte pour cette journée.")
                        break

                    if not m['cote_1'] or not m['cote_x'] or not m['cote_2']:
                        continue
                    action_id, details = predire_pari_zeus(model, m, conn)
                    mise_ar = details.get('montant_ar', 0)
                    
                    if mise_ar > 0 and details['type'] != 'Aucun':
                        # Mode Prudence : Si ZEUS a une dette, on réduit la mise de 50%
                        if dette_actuelle > 0:
                            mise_ar = int(mise_ar * 0.5)
                            print_verbose(f"   🛡️ [PRUDENCE ZEUS] Dette active ({dette_actuelle} Ar). Mise réduite à {mise_ar} Ar.")

                        # Protection contre les anomalies de solde négatif
                        if capital_actuel < 0:
                            logger.error(f"[ANOMALIE] Bankroll ZEUS négatif ({capital_actuel} Ar). Paris suspendus jusqu'à régularisation.")
                            print_verbose(f"   ⚠️ [ANOMALIE] Bankroll ZEUS négatif ({capital_actuel} Ar). Emprunt ou régularisation requis.")
                            break

                        # Stop-Loss (désactivable via override)
                        if capital_actuel < config.BANKROLL_STOP_LOSS and not override_stop_loss:
                            logger.warning(f"[STOP-LOSS] Bankroll ZEUS ({capital_actuel} Ar) sous le seuil ({config.BANKROLL_STOP_LOSS} Ar). Arrêt des paris ZEUS.")
                            print_verbose(f"   ⛔ [STOP-LOSS] Bankroll ZEUS ({capital_actuel} Ar) < {config.BANKROLL_STOP_LOSS} Ar. Paris suspendus (Override: Non).")
                            break
                        elif capital_actuel < config.BANKROLL_STOP_LOSS and override_stop_loss:
                            print_verbose(f"   🔓 [OVERRIDE] Bankroll ({capital_actuel} Ar) sous le seuil, mais passage autorisé par l'utilisateur.")
                        # Check if match is already in a combo
                        cursor.execute("""
                            SELECT COUNT(*) as count
                            FROM pari_multiple_items pmi
                            JOIN predictions p ON pmi.prediction_id = p.id
                            JOIN pari_multiple pm ON pmi.pari_multiple_id = pm.id
                            WHERE p.match_id = %s AND pm.session_id = %s AND pm.resultat IS NULL
                        """, (m['id'], session_id))
                        result = cursor.fetchone()
                        if result and result['count'] > 0:
                            logger.info(f"Match {m['equipe_dom_nom']} vs {m['equipe_ext_nom']} déjà présent dans le combiné du jour. Saut du pari simple ZEUS.")
                            continue

                        cursor.execute("""
                            INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                        """, (session_id, m['id'], details['type'], float(0.8), 'ZEUS'))
                        prediction_id = cursor.fetchone()['id']
                        bankroll_apres = capital_actuel - mise_ar
                        cote_value = m.get(f'cote_{details["type"].lower()}')
                        enregistrer_pari(
                            session_id=session_id,
                            prediction_id=prediction_id,
                            journee=journee,
                            type_pari=details['type'],
                            mise_ar=mise_ar,
                            pourcentage_bankroll=mise_ar / capital_actuel if capital_actuel > 0 else 0,
                            cote_jouee=float(cote_value) if cote_value else 0,
                            resultat=None,
                            profit_net=None,
                            bankroll_apres=bankroll_apres,
                            probabilite_implicite=1.0 / float(cote_value) if cote_value else None,
                            action_id=action_id,
                            conn=conn
                        )
                        capital_actuel = bankroll_apres
                        paris_engages += 1
                    predictions.append({
                        'match_id': m['id'],
                        'equipe_dom': m['equipe_dom_nom'],
                        'equipe_ext': m['equipe_ext_nom'],
                        'action_id': action_id,
                        'pari_type': details['type'],
                        'mise_ar': mise_ar,
                        'decision_formatee': formater_decision_zeus(details)
                    })
    except Exception as e:
        logger.error(f"Erreur prédictions ZEUS J{journee} : {e}")
    return predictions
def mettre_a_jour_scoring():
    try:
        with get_db_connection(write=True) as conn:
            active_session = get_active_session(conn=conn)
            session_id = active_session['id']
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p.id, p.prediction, m.score_dom, m.score_ext 
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                WHERE p.session_id = %s AND p.succes IS NULL
            ''', (session_id,))
            en_attente = cursor.fetchall()
            for p in en_attente:
                pid, pred, sd, se = p['id'], p['prediction'], p['score_dom'], p['score_ext']
                if sd is None or se is None:
                    continue
                resultat_reel = "1" if sd > se else ("2" if se > sd else "X")
                succes = 1 if resultat_reel == pred else 0
                cursor.execute('''
                    UPDATE predictions 
                    SET resultat = %s, succes = %s
                    WHERE id = %s
                ''', (resultat_reel, succes, pid))
                pts = config.PRISMA_POINTS_VICTOIRE if succes == 1 else config.PRISMA_POINTS_DEFAITE
                cursor.execute('''
                        UPDATE sessions 
                        SET score_prisma = score_prisma + %s
                        WHERE id = %s
                    ''', (pts, session_id))
            multiple_bets.valider_paris_multiples(conn=conn)
            valider_paris_zeus(conn)
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du scoring : {e}", exc_info=True)
        print_verbose(f"❌ Erreur lors de la mise à jour du scoring : {e}")
        return
    print_verbose("Mise a jour du scoring terminee.")
