import logging
from typing import List, Dict
import importlib
import sys
import functools
import threading
from ..core import config
from ..core.database import get_db_connection
from ..core.session_manager import get_active_session
from ..prisma import engine as prisma_engine
from ..prisma import selection as prisma_selection
from ..zeus.models.inference import get_zeus_model, predire_pari_zeus, formater_decision_zeus
from ..zeus.database.queries import get_matches_for_journee, enregistrer_pari, valider_paris_zeus, PariRecord
from . import multiple_bets
from ..core.console import console, print_verbose
from ..core.zeus_finance import get_zeus_bankroll, update_zeus_bankroll
from ..core.prisma_finance import get_prisma_bankroll, is_prisma_stop_loss_active
from ..core.risk_engine import get_risk_engine, BetRequest, ValidationStatus
from ..core.utils import safe_json_dumps

logger = logging.getLogger(__name__)

# Variables globales pour la gestion de l'entraînement asynchrone
_training_lock = threading.Lock()
_training_in_progress = False

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
        return None, 0, {}

def _calculer_probabilite_amelioree_internal(conn, session_id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2):
    cursor = conn.cursor()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = %s AND equipe_id = %s ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
    stats_dom = cursor.fetchone()
    cursor.execute("SELECT points, forme FROM classement WHERE session_id = %s AND equipe_id = %s ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
    stats_ext = cursor.fetchone()
    if not stats_dom or not stats_ext:
        return None, 0, {}
    pts_dom, forme_dom = stats_dom['points'], stats_dom['forme']
    pts_ext, forme_ext = stats_ext['points'], stats_ext['forme']
    buts_dom = analyser_buts_recents_internal(cursor, session_id, equipe_id=equipe_dom_id)
    buts_ext = analyser_buts_recents_internal(cursor, session_id, equipe_id=equipe_ext_id)
    bonus_h2h = analyser_confrontations_directes(equipe_dom_id, equipe_ext_id, conn=conn)
    prisma_data = {
        'equipe_dom_id': equipe_dom_id,
        'equipe_ext_id': equipe_ext_id,
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
    prediction, score, metadata = prisma_engine.calculer_score_prisma_v2(prisma_data, conn=conn)
    if prediction is None:
        return None, 0, {}
    # Injecter les cotes dans metadata pour faciliter Kelly plus tard
    metadata.update({'cote_1': cote_1, 'cote_x': cote_x, 'cote_2': cote_2})
    return prediction, score, metadata

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
        cursor.execute("""
            INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (session_id, match_id, source) DO UPDATE SET
                prediction = EXCLUDED.prediction,
                fiabilite = EXCLUDED.fiabilite
        """, (session_id, p['match_id'], p['prediction'], p['fiabilite'], 'PRISMA'))
    return predictions

def selectionner_meilleurs_matchs_ameliore(journee, conn=None):
    _reload_config()
    min_journee = getattr(config, 'PRISMA_AMELIORE_MIN_JOURNEE', 4)
    if journee < min_journee:
        print_verbose(f"Info : Journée {journee} < {min_journee} (seuil PRISMA amélioré). Pas assez de données.")
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
    raw_predictions = []
    for m in matchs:
        match_id, dom_id, ext_id, c1, cx, c2 = m['id'], m['equipe_dom_id'], m['equipe_ext_id'], m['cote_1'], m['cote_x'], m['cote_2']
        pred, conf, meta = calculer_probabilite_amelioree(dom_id, ext_id, c1, cx, c2, conn=conn)
        
        if pred == 'NO_BET':
            reason = meta.get('reason', 'Silence Intelligent')
            print_verbose(f"   🔇 [PRISMA SILENCE] {equipes_noms.get(dom_id)} vs {equipes_noms.get(ext_id)} rejeté : {reason}")
            continue

        if pred:
            conf_final = float(conf)
            incertain_str = " ⚠️ [Match incertain]" if conf_final < 0.45 else ""
            print_verbose(f"   [PRISMA] {equipes_noms.get(dom_id)} vs {equipes_noms.get(ext_id)} | Score: {conf_final:.2f}{incertain_str}")

            # --- Ajustement Dynamique du Seuil ---
            # Si la source est l'Ensemble ML, le score est une probabilité (0-1)
            # Sinon (Fallback), c'est un score PRISMA classique (0-15+)
            is_ml = meta.get('source', '').startswith('Ensemble') or meta.get('source', '').startswith('ML')
            
            if is_ml:
                # Seuils de probabilité pour l'IA (équivalents aux seuils 7-10 classiques)
                if seuil_confiance >= 10.0: # Mode Crise
                    seuil_ml = 0.85
                elif seuil_confiance >= 8.5: # Mode Prudent
                    seuil_ml = 0.75
                elif seuil_confiance <= 6.0: # Mode Offensif
                    seuil_ml = 0.60
                else: # Standard
                    seuil_ml = 0.70
                
                authorized = conf_final >= seuil_ml
                print_verbose(f"   [PRISMA ML] {equipes_noms.get(dom_id)} vs {equipes_noms.get(ext_id)} | Conf: {conf_final:.2f} (Seuil IA: {seuil_ml}) {'✅' if authorized else '❌'}")
            else:
                authorized = conf_final >= seuil_confiance
                print_verbose(f"   [PRISMA CLASSIQUE] {equipes_noms.get(dom_id)} vs {equipes_noms.get(ext_id)} | Score: {conf_final:.2f} (Seuil: {seuil_confiance}) {'✅' if authorized else '❌'}")

            if authorized:
                raw_predictions.append({
                    'match_id': match_id, 'equipe_dom_id': dom_id, 'equipe_ext_id': ext_id,
                    'equipe_dom': equipes_noms.get(dom_id), 'equipe_ext': equipes_noms.get(ext_id),
                    'prediction': pred, 'confiance': conf_final, 'fiabilite': conf_final,
                    'ai_analysis': None, 'score_base': float(conf),
                    'cote_1': c1, 'cote_x': cx, 'cote_2': c2,
                    'meta': meta
                })
    final_selection = prisma_selection.filtrer_meilleurs_matchs(raw_predictions, config.MAX_PREDICTIONS_PAR_JOURNEE)
    
    from core.prisma_finance import deduct_prisma_funds, get_prisma_bankroll

    # Phase 2 : Enregistrement des prédictions DB
    for p in final_selection:
        tech_json_str = safe_json_dumps(p.get('meta', {}))
        
        cursor.execute("""
            INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source, technical_details, ai_analysis, ai_advice)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id, match_id, source) DO UPDATE SET
                prediction = EXCLUDED.prediction,
                fiabilite = EXCLUDED.fiabilite,
                technical_details = EXCLUDED.technical_details,
                ai_analysis = EXCLUDED.ai_analysis,
                ai_advice = EXCLUDED.ai_advice
            RETURNING id
        """, (session_id, p['match_id'], p['prediction'], p['fiabilite'], 'PRISMA', tech_json_str, None, None))
        pred_id = cursor.fetchone()['id']
        p['id'] = pred_id

    # Phase 3 : Pari Multiple (Combiné) prioritaire — nécessite min 2 matchs validés
    multiple_result = None
    selections_combinable = []
    for p in final_selection:
        cote_key = "cote_x" if p["prediction"].upper() in ["N", "X"] else f"cote_{p['prediction'].lower()}"
        cote_val = p.get(cote_key)
        if cote_val and float(cote_val) <= getattr(config, 'MAX_COMBINED_ODDS', 5.0):
            selections_combinable.append(p)
    if len(selections_combinable) >= 2:
        multiple_result = multiple_bets.generer_pari_multiple(journee, selections_combinable, conn=conn)

    # Phase 4 : Paris Simples (SEULEMENT si le pari multiple n'a pas été placé)
    if not multiple_result:
        for p in final_selection:
            # Filtrer les cotes trop élevées pour les paris simples aussi
            cote_key_p = "cote_x" if p["prediction"].upper() in ["N", "X"] else f"cote_{p['prediction'].lower()}"
            cote_val_p = p.get(cote_key_p)
            if cote_val_p and float(cote_val_p) > getattr(config, 'MAX_COMBINED_ODDS', 5.0):
                logger.info(f"[PRISMA] Pari simple rejeté pour {p.get('equipe_dom')} vs {p.get('equipe_ext')} : cote {float(cote_val_p):.2f} > plafond {config.MAX_COMBINED_ODDS}")
                continue

            # Place Simple Bet for PRISMA
            # On utilise Kelly si activé et qu'on a des probabilités ML dispo
            if getattr(config, 'PRISMA_KELLY_ENABLED', False) and p.get('meta'):
                from ..prisma import kelly
                bankroll = get_prisma_bankroll()
                # On privilégie la probabilité calibrée du modèle ML si présente
                prob_ml = p['meta'].get('confidence')
                
                if prob_ml:
                    cote_key = "cote_x" if p["prediction"].upper() in ["N", "X"] else f"cote_{p['prediction'].lower()}"
                    cote_val = p.get(cote_key)
                    mise_ar = kelly.calculate_kelly_stake(
                        probability=prob_ml,
                        odds=float(cote_val) if cote_val else 0,
                        bankroll=bankroll,
                        fraction=getattr(config, 'PRISMA_KELLY_FRACTION', 0.2),
                        max_stake=getattr(config, 'PRISMA_MAX_STAKE', 2000),
                        min_stake=getattr(config, 'PRISMA_MIN_STAKE', 1000)
                    )
                else:
                     # Fallback mise fixe si pas de probas
                     mise_ar = config.MONTANT_FIXE_MULTIPLE if config.USE_MONTANT_FIXE else int(bankroll * 0.05)
            else:
                # Fallback historique
                mise_ar = config.MONTANT_FIXE_MULTIPLE if config.USE_MONTANT_FIXE else int(get_prisma_bankroll() * 0.05)
            
            # Sécurité minimale
            if mise_ar <= 0:
                logger.info(f"[PRISMA] Saut du pari pour {p['equipe_dom']} (Mise Kelly null ou espérance négative)")
                continue

            fonds_suffisants, current_bankroll = deduct_prisma_funds(mise_ar)
            if fonds_suffisants:
                cote_val = p.get('cote_1') if p['prediction'] == '1' else (p.get('cote_x') if p['prediction'] in ['X', 'N'] else p.get('cote_2'))
                enregistrer_pari(
                    PariRecord(
                        session_id=session_id,
                        prediction_id=p['id'],
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
                        strategie='PRISMA'
                    ),
                    conn=conn
                )
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
        from ..prisma.analyzers import analyser_confrontations_directes_prisma
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                return analyser_confrontations_directes_prisma(cursor, session_id, equipe_dom_id, equipe_ext_id)
    except: return 0


def analyser_confrontations_directes(equipe_dom_id, equipe_ext_id, conn=None):
    if conn:
        active_session = get_active_session(conn=conn)
    else:
        active_session = get_cached_active_session()
    
    session_id = active_session['id']
    if conn:
        from ..prisma.analyzers import analyser_confrontations_directes_prisma
        with conn.cursor() as cursor:
            return analyser_confrontations_directes_prisma(cursor, session_id, equipe_dom_id, equipe_ext_id)
    return analyser_confrontations_directes_cached(session_id, equipe_dom_id, equipe_ext_id)



def obtenir_predictions_zeus_journee(journee: int) -> List[Dict]:
    _reload_config()
    model = get_zeus_model()
    if not model:
        logger.warning("Modèle ZEUS non trouvé pour l'inférence.")
        return []
    active_session = get_active_session()
    session_id = active_session['id']
    all_predictions = []
    try:
        with get_db_connection(write=True) as conn:
            matches = get_matches_for_journee(journee, conn)
            cursor = conn.cursor()
            # 1. Collecter TOUTES les opportunités ZEUS d'abord
            candidates = []
            for m in matches:
                if not m['cote_1'] or not m['cote_x'] or not m['cote_2']:
                    continue
                
                action_id, details = predire_pari_zeus(model, m, conn)
                if details.get('montant_ar', 0) > 0 and details['type'] != 'Aucun':
                    candidates.append({
                        'match': m,
                        'match_id': m['id'],
                        'equipe_dom': m['equipe_dom_nom'],
                        'equipe_ext': m['equipe_ext_nom'],
                        'action_id': action_id,
                        'prediction': details['type'],
                        'pari_type': details['type'],
                        'details': details,
                        'mise_ar': details.get('montant_ar', 0),
                        'decision_formatee': formater_decision_zeus(details)
                    })

            if not candidates:
                return []

            # 2. Phase Prioritaire : Pari Combiné (Multiple) si au moins 2 opportunités
            multiple_result = None
            ids_in_multiple = set()
            
            if len(candidates) >= 2:
                # ZEUS prend exactement les 2 premiers matchs pour son combiné
                print_verbose(f"   🎯 [ZEUS] Tentative de pari combiné avec {len(candidates)} opportunités...")
                multiple_result = multiple_bets.generer_pari_multiple(journee, candidates[:2], strategie='ZEUS', conn=conn)
                
                if multiple_result:
                    # Marquer les matchs comme étant dans le combiné
                    ids_in_multiple = {c['match_id'] for c in candidates[:2]}
                    # Ajouter à la liste de retour pour visibilité
                    for c in candidates[:2]:
                        c['in_multiple'] = True
                        all_predictions.append(c)
                    logger.info(f"[ZEUS] ✅ Pari combiné placé. Paris simples supprimés pour ces matchs.")
                else:
                    # Le combiné a échoué (stop-loss, fonds insuffisants, etc.) :
                    # On ne place PAS de paris simples sur ces matchs pour éviter le double-pari
                    ids_in_multiple = {c['match_id'] for c in candidates[:2]}
                    logger.warning(f"[ZEUS] ⚠️ Pari combiné échoué. Les {len(ids_in_multiple)} matchs concernés sont exclus des paris simples.")
            
            # 3. Phase Secondaire : Paris Simples pour les matchs restants
            capital_actuel = get_zeus_bankroll(conn=conn)
            cursor.execute("SELECT dette_zeus, stop_loss_override FROM sessions WHERE id = %s", (session_id,))
            sess_row = cursor.fetchone()
            dette_actuelle = sess_row['dette_zeus'] if sess_row else 0
            override_stop_loss = sess_row['stop_loss_override'] if sess_row else False
            
            # Limite de paris par jour (compte le combiné s'il existe)
            limite_journaliere = 1 if dette_actuelle > 0 else 3
            paris_engages = 1 if multiple_result else 0
            
            risk_engine = get_risk_engine()

            for c in candidates:
                # Sauter si déjà dans le combiné
                if c['match_id'] in ids_in_multiple:
                    continue
                
                # Vérifier limite
                if paris_engages >= limite_journaliere:
                    print_verbose(f"   🛑 [LIMITE ZEUS] Limite de {limite_journaliere} paris atteinte.")
                    break

                m = c['match']
                details = c['details']
                mise_ar = c['mise_ar']

                # Mode Prudence : Si ZEUS a une dette, on réduit la mise de 50%
                if dette_actuelle > 0:
                    mise_ar = int(mise_ar * 0.5)

                # Protection bankroll & stop-loss
                if capital_actuel < 0:
                    logger.error(f"[ANOMALIE] Bankroll ZEUS négatif. Paris stoppés.")
                    break

                if capital_actuel < config.BANKROLL_STOP_LOSS and not override_stop_loss:
                    print_verbose(f"   ⛔ [STOP-LOSS] Bankroll ZEUS sous le seuil.")
                    break

                # === VALIDATION RISK ENGINE ===
                cote_key = 'cote_x' if details["type"] == 'N' else f'cote_{details["type"].lower()}'
                cote_value = m.get(cote_key, 0)
                
                bet_request = BetRequest(
                    agent='ZEUS',
                    session_id=session_id,
                    journee=journee,
                    match_id=m['id'],
                    bet_type=details['type'],
                    amount=mise_ar,
                    odds=float(cote_value) if cote_value else 0.0,
                    confidence=0.8,
                    zeus_score=details.get('score', 0.6)
                )
                
                validation_result = risk_engine.validate_bet(bet_request)
                
                if validation_result.status != ValidationStatus.ACCEPTED:
                    logger.warning(f"[RISK-ENGINE] Pari ZEUS refusé: {validation_result.message}")
                    continue
                
                # Exécution du pari simple
                if validation_result.adjusted_amount:
                    mise_ar = validation_result.adjusted_amount

                cursor.execute("""
                    INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (session_id, match_id, source) DO UPDATE SET
                        prediction = EXCLUDED.prediction,
                        fiabilite = EXCLUDED.fiabilite
                    RETURNING id
                """, (session_id, m['id'], details['type'], float(0.8), 'ZEUS'))
                prediction_id = cursor.fetchone()['id']
                
                bankroll_apres = capital_actuel - mise_ar
                enregistrer_pari(
                    PariRecord(
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
                        action_id=c['action_id'],
                        strategie='ZEUS'
                    ),
                    conn=conn
                )
                update_zeus_bankroll(bankroll_apres, conn=conn)
                capital_actuel = bankroll_apres
                paris_engages += 1
                
                c['id'] = prediction_id
                c['mise_ar'] = mise_ar
                all_predictions.append(c)
                logger.info(f"[ZEUS] ✓ Pari simple validé: {m['equipe_dom_nom']} vs {m['equipe_ext_nom']}")

    except Exception as e:
        logger.error(f"Erreur prédictions ZEUS J{journee} : {e}", exc_info=True)
    
    return all_predictions

def check_training_needs():
    """Vérification robuste des besoins d'entraînement (Session + Volume)."""
    try:
        from prisma import xgboost_model
        with get_db_connection() as conn:
            active_session = get_active_session(conn=conn)
            if not active_session:
                return False
            
            current_session_id = active_session['id']
            current_day = active_session.get('current_day', 1)
            
            # 1. Vérifier si un entraînement est déjà en cours
            with _training_lock:
                if _training_in_progress:
                    return False
            
            # 2. Vérifier les métadonnées pour changement de session
            meta = xgboost_model.get_model_metadata()
            last_session = meta.get('last_training_session', 0) if meta else 0
            
            if current_session_id > last_session:
                logger.info(f"[IA-BOOSTER] Transition de session détectée ({last_session} -> {current_session_id})")
                return True

            # 3. Vérification par volume (toutes les 10 journées)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(id) AS cnt FROM matches WHERE session_id = %s AND score_dom IS NOT NULL", (current_session_id,))
            matchs_termines = cursor.fetchone()['cnt']
            
            return matchs_termines > 0 and matchs_termines % 10 == 0
            
    except Exception as e:
        logger.warning(f"[IA-BOOSTER] Erreur vérification training: {e}")
        return False


def _train_ensemble_async():
    """Exécute le pipeline complet PRISMA Intelligence++ de manière asynchrone."""
    global _training_in_progress
    
    try:
        logger.info("[IA-BOOSTER] 🚀 DÉMARRAGE PIPELINE PRISMA INTELLIGENCE++ (Background)")
        with get_db_connection(write=True) as conn:
            from prisma.orchestrator import PrismaIntelligenceOrchestrator
            
            orchestrator = PrismaIntelligenceOrchestrator(conn)
            # On exécute Audit -> Train -> Validate -> Feedback -> Monitor
            results = orchestrator.run_full_pipeline()
            
            if results and 'training' in results and results['training']['status'] == 'success':
                logger.info("[IA-BOOSTER] ✅ Pipeline PRISMA terminé avec succès")
            else:
                 logger.warning("[IA-BOOSTER] ⚠️ Pipeline terminé avec des erreurs partielles")
                 
    except Exception as e:
        logger.error(f"[IA-BOOSTER] ❌ Erreur critique dans le pipeline asynchrone: {e}")
    finally:
        with _training_lock:
            _training_in_progress = False
        logger.info("[IA-BOOSTER] Verrou de pipeline libéré")


def mettre_a_jour_scoring():
    global _training_in_progress
    try:
        with get_db_connection(write=True) as conn:
            active_session = get_active_session(conn=conn)
            session_id = active_session['id']
            
            # --- Auto-retrain Ensemble ML (XGBoost + CatBoost) ---
            if getattr(config, 'PRISMA_XGBOOST_ENABLED', False):
                try:
                    # Vérification rapide non-bloquante
                    needs_training = check_training_needs()
                    
                    if needs_training:
                        # Vérifier si un entraînement est déjà en cours
                        with _training_lock:
                            if _training_in_progress:
                                logger.info("[ENSEMBLE] Entraînement déjà en cours, skip...")
                            else:
                                _training_in_progress = True
                                logger.info("[ENSEMBLE] Lancement entraînement asynchrone")
                                # Lancer l'entraînement dans un thread séparé
                                training_thread = threading.Thread(
                                    target=_train_ensemble_async,
                                    daemon=True  # Thread daemon pour ne pas bloquer la fermeture du programme
                                )
                                training_thread.start()
                                logger.info("[ENSEMBLE] Entraînement lancé en arrière-plan, continuation du monitoring...")
                except Exception as e:
                    logger.warning(f"[ENSEMBLE] Auto-retrain check échoué: {e}")

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
