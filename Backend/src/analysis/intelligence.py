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
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
    stats_dom = cursor.fetchone()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
    stats_ext = cursor.fetchone()
    if not stats_dom or not stats_ext:
        return None, 0
    pts_dom, forme_dom = stats_dom
    pts_ext, forme_ext = stats_ext
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
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
    stats_dom = cursor.fetchone()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
    stats_ext = cursor.fetchone()
    if not stats_dom or not stats_ext:
        return None, 0
    pts_dom, forme_dom = stats_dom
    pts_ext, forme_ext = stats_ext
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
    cursor.execute("SELECT succes FROM predictions WHERE session_id = ? AND succes IS NOT NULL ORDER BY id DESC LIMIT 15", (session_id,))
    resultats = cursor.fetchall()
    if not resultats: return 1.0, "Neutre"
    succes_count = sum(1 for r in resultats if r[0] == 1)
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
    cursor.execute("SELECT id, equipe_dom_id, equipe_ext_id FROM matches WHERE session_id = ? AND journee = ?", (session_id, journee))
    matchs = cursor.fetchall()
    predictions = []
    for m in matchs:
        match_id, dom_id, ext_id = m
        pred, conf = calculer_probabilite(dom_id, ext_id, conn=conn)
        if pred:
            predictions.append({
                'match_id': match_id,
                'prediction': pred,
                'fiabilite': conf
            })
    for p in predictions:
        cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source) VALUES (?, ?, ?, ?, ?)",
                     (session_id, p['match_id'], p['prediction'], p['fiabilite'], 'PRISMA'))
    return predictions
def selectionner_meilleurs_matchs_ameliore(journee, conn=None):
    _reload_config()
    if getattr(config, 'ZEUS_DEEP_SLEEP', False):
        print(f"💤 [IA] Sommeil Profond actif (Entraînement ZEUS). Aucune prédiction.")
        return []
    if journee < 4:
        print(f"Info : Journée {journee} < 4. Pas assez de données.")
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
        print(f"   ⛔ [STOP-LOSS] Bankroll PRISMA sous {config.BANKROLL_STOP_LOSS} Ar. Aucune prédiction PRISMA générée.")
        logger.warning(f"[STOP-LOSS] Bankroll PRISMA sous seuil. Paris PRISMA suspendus.")
        return []
    cursor = conn.cursor()
    taux_succes, _ = analyser_performances_recentes(conn=conn)
    seuil_confiance, mode_descr = prisma_selection.determiner_seuil_dynamique(taux_succes)
    print(f"   [PRISMA] Mode {mode_descr} | Seuil: {seuil_confiance}")
    cursor.execute("SELECT id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2 FROM matches WHERE session_id = ? AND journee = ?", (session_id, journee))
    matchs = cursor.fetchall()
    cursor.execute("SELECT id, nom FROM equipes")
    equipes_noms = {r[0]: r[1] for r in cursor.fetchall()}
    raw_predictions = []
    for m in matchs:
        match_id, dom_id, ext_id, c1, cx, c2 = m
        pred, conf = calculer_probabilite_amelioree(dom_id, ext_id, c1, cx, c2, conn=conn)
        if pred and conf >= seuil_confiance:
            raw_predictions.append({
                'match_id': match_id, 'equipe_dom_id': dom_id, 'equipe_ext_id': ext_id,
                'equipe_dom': equipes_noms.get(dom_id), 'equipe_ext': equipes_noms.get(ext_id),
                'prediction': pred, 'confiance': conf, 'fiabilite': conf
            })
    final_selection = prisma_selection.filtrer_meilleurs_matchs(raw_predictions, config.MAX_PREDICTIONS_PAR_JOURNEE)
    for p in final_selection:
        cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source) VALUES (?, ?, ?, ?, ?)",
                     (session_id, p['match_id'], p['prediction'], p['fiabilite'], 'PRISMA'))
        p['id'] = cursor.lastrowid
    multiple_bets.generer_pari_multiple(journee, final_selection, conn=conn)
    return final_selection
def analyser_buts_recents_internal(cursor, session_id, equipe_id):
    try:
        cursor.execute("""
            SELECT 
                CASE WHEN equipe_dom_id = ? THEN score_dom ELSE score_ext END,
                CASE WHEN equipe_dom_id = ? THEN score_ext ELSE score_dom END
            FROM matches 
            WHERE session_id = ? AND (equipe_dom_id = ? OR equipe_ext_id = ?) AND score_dom IS NOT NULL
            ORDER BY journee DESC LIMIT 5
        """, (equipe_id, equipe_id, session_id, equipe_id, equipe_id))
        res = cursor.fetchall()
        if not res: return None
        return sum(r[0] for r in res), sum(r[1] for r in res)
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
        WHERE session_id = ? AND equipe_dom_id = ? AND equipe_ext_id = ? AND score_dom IS NOT NULL
        ORDER BY journee DESC LIMIT 5
    """, (session_id, equipe_dom_id, equipe_ext_id))
    hist = cursor.fetchall()
    if not hist or len(hist) < 3: return 0
    v_dom = sum(1 for h in hist if h[0] > h[1])
    nuls = sum(1 for h in hist if h[0] == h[1])
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
            cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = ? ORDER BY id_pari DESC LIMIT 1", (session_id,))
            row = cursor.fetchone()
            capital_actuel = row[0] if row else active_session['capital_initial']
            model = get_zeus_model()
            if model:
                for m in matches:
                    if not m['cote_1'] or not m['cote_x'] or not m['cote_2']:
                        continue
                    action_id, details = predire_pari_zeus(model, m, conn)
                    mise_ar = details.get('montant_ar', 0)
                    if mise_ar > 0 and details['type'] != 'Aucun':
                        if capital_actuel < config.BANKROLL_STOP_LOSS:
                            logger.warning(f"[STOP-LOSS] Bankroll ZEUS ({capital_actuel} Ar) sous le seuil ({config.BANKROLL_STOP_LOSS} Ar). Arrêt des paris ZEUS.")
                            print(f"   ⛔ [STOP-LOSS] Bankroll ZEUS ({capital_actuel} Ar) < {config.BANKROLL_STOP_LOSS} Ar. Paris suspendus.")
                            break
                        # Check if match is already in a combo
                        cursor.execute("""
                            SELECT COUNT(*) 
                            FROM pari_multiple_items pmi
                            JOIN predictions p ON pmi.prediction_id = p.id
                            JOIN pari_multiple pm ON pmi.pari_multiple_id = pm.id
                            WHERE p.match_id = ? AND pm.session_id = ? AND pm.resultat IS NULL
                        """, (m['id'], session_id))
                        if cursor.fetchone()[0] > 0:
                            logger.info(f"Match {m['equipe_dom_nom']} vs {m['equipe_ext_nom']} déjà présent dans le combiné du jour. Saut du pari simple ZEUS.")
                            continue

                        cursor.execute("""
                            INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source)
                            VALUES (?, ?, ?, ?, ?)
                        """, (session_id, m['id'], details['type'], 0.8, 'ZEUS'))
                        prediction_id = cursor.lastrowid
                        bankroll_apres = capital_actuel - mise_ar
                        enregistrer_pari(
                            session_id=session_id,
                            prediction_id=prediction_id,
                            journee=journee,
                            type_pari=details['type'],
                            mise_ar=mise_ar,
                            pourcentage_bankroll=mise_ar / capital_actuel if capital_actuel > 0 else 0,
                            cote_jouee=m.get(f'cote_{details["type"].lower()}', 0),
                            resultat=None,
                            profit_net=None,
                            bankroll_apres=bankroll_apres,
                            probabilite_implicite=1.0 / m.get(f'cote_{details["type"].lower()}', 1) if m.get(f'cote_{details["type"].lower()}') else None,
                            action_id=action_id,
                            conn=conn
                        )
                        capital_actuel = bankroll_apres
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
                WHERE p.session_id = ? AND p.succes IS NULL
            ''', (session_id,))
            en_attente = cursor.fetchall()
            for p in en_attente:
                pid, pred, sd, se = p
                if sd is None or se is None:
                    continue
                resultat_reel = "1" if sd > se else ("2" if se > sd else "X")
                succes = 1 if resultat_reel == pred else 0
                cursor.execute('''
                    UPDATE predictions 
                    SET resultat = ?, succes = ?
                    WHERE id = ?
                ''', (resultat_reel, succes, pid))
                pts = config.PRISMA_POINTS_VICTOIRE if succes == 1 else config.PRISMA_POINTS_DEFAITE
                cursor.execute('''
                        UPDATE sessions 
                        SET score_prisma = score_prisma + ?
                        WHERE id = ?
                    ''', (pts, session_id))
            multiple_bets.valider_paris_multiples(conn=conn)
            valider_paris_zeus(conn)
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du scoring : {e}", exc_info=True)
        print(f"❌ Erreur lors de la mise à jour du scoring : {e}")
        return
    print("Mise a jour du scoring terminee.")
