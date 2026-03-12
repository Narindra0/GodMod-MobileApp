import logging
import importlib
import sys
from ..core import config
from ..core.database import get_db_connection
from ..core.session_manager import get_active_session
from ..prisma import engine as prisma_engine
from ..prisma import selection as prisma_selection
from ..zeus.models.inference import get_zeus_model, predire_pari_zeus, formater_decision_zeus
from ..zeus.database.queries import get_matches_for_journee

logger = logging.getLogger(__name__)

def _reload_config():
    """Recharge le module config pour prendre en compte les changements depuis le dashboard."""
    if 'src.core.config' in sys.modules:
        importlib.reload(sys.modules['src.core.config'])
        # Réassigner la référence locale
        globals()['config'] = sys.modules['src.core.config']

def calculer_probabilite_avec_fallback(equipe_dom_id, equipe_ext_id, cote_1=None, cote_x=None, cote_2=None):
    """
    Phase 2 : Utilise toujours le calcul PRISMA, avec fallback vers l'ancien si les cotes manquent.
    """
    if cote_1 is not None and cote_x is not None and cote_2 is not None:
        return calculer_probabilite_amelioree(equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2)
    else:
        logger.warning(f"Cotes manquantes pour match {equipe_dom_id} vs {equipe_ext_id}. Utilisation du calcul simple.")
        return calculer_probabilite(equipe_dom_id, equipe_ext_id)

def calculer_probabilite(equipe_dom_id, equipe_ext_id):
    """
    Calcule une probabilité simplifiée basée sur le classement et la forme.
    Renvoie une recommandation (1, X, ou 2) et un score de confiance.
    """
    active_session = get_active_session()
    session_id = active_session['id']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
            stats_dom = cursor.fetchone()
            
            cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
            stats_ext = cursor.fetchone()
    except Exception as e:
        logger.error(f"Erreur lors du calcul de probabilité : {e}", exc_info=True)
        return None, 0
    
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


# ============================================
# PHASE 3 : RÉFÉRENTIEL PRISMA
# ============================================

def calculer_probabilite_amelioree(equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2):
    """
    Interface PRISMA pour le calcul amélioré.
    Prépare les données à partir de la DB et délègue au moteur PRISMA.
    """
    active_session = get_active_session()
    session_id = active_session['id']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Recup Stats
            cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_dom_id,))
            stats_dom = cursor.fetchone()
            
            cursor.execute("SELECT points, forme FROM classement WHERE session_id = ? AND equipe_id = ? ORDER BY journee DESC LIMIT 1", (session_id, equipe_ext_id,))
            stats_ext = cursor.fetchone()
            
            if not stats_dom or not stats_ext:
                return None, 0
            
            pts_dom, forme_dom = stats_dom
            pts_ext, forme_ext = stats_ext
            
            # Recup Buts
            buts_dom = analyser_buts_recents_internal(cursor, equipe_dom_id)
            buts_ext = analyser_buts_recents_internal(cursor, equipe_ext_id)
            
            # Recup H2H
            bonus_h2h = analyser_confrontations_directes(equipe_dom_id, equipe_ext_id)
            
            # Préparation du pack de données pour PRISMA
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

            # Délégation au moteur PRISMA
            prediction, score = prisma_engine.calculer_score_prisma(prisma_data)
            
            if prediction is None:
                # Log du motif de rejet PRISMA si nécessaire
                # logger.info(f"[PRISMA] Match rejeté : {score}")
                return None, 0
            
            return prediction, score
            
    except Exception as e:
        logger.error(f"Erreur lors du calcul PRISMA : {e}", exc_info=True)
        return None, 0


def analyser_performances_recentes():
    """Analyse les performances récentes (DB)."""
    active_session = get_active_session()
    session_id = active_session['id']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT succes FROM predictions WHERE session_id = ? AND succes IS NOT NULL ORDER BY id DESC LIMIT 15", (session_id,))
            resultats = cursor.fetchall()
            if not resultats: return 1.0, "Neutre"
            succes_count = sum(1 for r in resultats if r[0] == 1)
            return succes_count / len(resultats), f"{succes_count}/{len(resultats)}"
    except Exception as e:
        logger.error(f"Erreur DB performances : {e}")
        return 1.0, "Erreur"

def selectionner_meilleurs_matchs(journee):
    """
    Sélection standard basée sur le calcul de probabilité simple.
    """
    _reload_config()
    active_session = get_active_session()
    session_id = active_session['id']
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Récupération des matchs
            cursor.execute("SELECT id, equipe_dom_id, equipe_ext_id FROM matches WHERE session_id = ? AND journee = ?", (session_id, journee))
            matchs = cursor.fetchall()
            
            predictions = []
            for m in matchs:
                match_id, dom_id, ext_id = m
                pred, conf = calculer_probabilite(dom_id, ext_id)
                
                if pred:
                    predictions.append({
                        'match_id': match_id,
                        'prediction': pred,
                        'fiabilite': conf
                    })
            
            # Sauvegarde
            for p in predictions:
                cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite) VALUES (?, ?, ?, ?)",
                             (session_id, p['match_id'], p['prediction'], p['fiabilite']))
            
            return predictions
    except Exception as e:
        logger.error(f"Erreur sélection standard : {e}")
        return []

def selectionner_meilleurs_matchs_ameliore(journee):
    """
    Sélection intelligente déléguée à PRISMA avec orchestration DB.
    Respecte le mode 'Sommeil Profond' pendant l'entraînement de ZEUS.
    """
    _reload_config()
    
    # 0. Vérif Sommeil Profond (ZEUS Training)
    if getattr(config, 'ZEUS_DEEP_SLEEP', False):
        print(f"💤 [IA] Sommeil Profond actif (Entraînement ZEUS). Aucune prédiction.")
        return []
        
    if journee < 4:
        print(f"Info : Journée {journee} < 4. Pas assez de données.")
        return []
    
    active_session = get_active_session()
    session_id = active_session['id']
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 2. IA Adaptative (PRISMA)
            taux_succes, ratio_str = analyser_performances_recentes()
            seuil_confiance, mode_descr = prisma_selection.determiner_seuil_dynamique(taux_succes)
            print(f"   [PRISMA] Mode {mode_descr} | Seuil: {seuil_confiance}")
            
            # 3. Récupération & Analyse des matchs pour la session active
            cursor.execute("SELECT id, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2 FROM matches WHERE session_id = ? AND journee = ?", (session_id, journee))
            matchs = cursor.fetchall()
            
            cursor.execute("SELECT id, nom FROM equipes")
            equipes_noms = {r[0]: r[1] for r in cursor.fetchall()}
            
            raw_predictions = []
            for m in matchs:
                match_id, dom_id, ext_id, c1, cx, c2 = m
                pred, conf = calculer_probabilite_amelioree(dom_id, ext_id, c1, cx, c2)
                
                if pred and conf >= seuil_confiance:
                    raw_predictions.append({
                        'match_id': match_id, 'equipe_dom_id': dom_id, 'equipe_ext_id': ext_id,
                        'equipe_dom': equipes_noms.get(dom_id), 'equipe_ext': equipes_noms.get(ext_id),
                        'prediction': pred, 'confiance': conf, 'fiabilite': conf
                    })
            
            # 4. Sélection déléguée
            final_selection = prisma_selection.filtrer_meilleurs_matchs(raw_predictions, config.MAX_PREDICTIONS_PAR_JOURNEE)
            
            # 5. DB Save avec session_id
            for p in final_selection:
                cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite) VALUES (?, ?, ?, ?)",
                             (session_id, p['match_id'], p['prediction'], p['fiabilite']))
            
            return final_selection
            
    except Exception as e:
        logger.error(f"Erreur sélection PRISMA : {e}", exc_info=True)
        return []


def analyser_buts_recents_internal(cursor, equipe_id):
    """Analyse les buts (Helper DB)."""
    active_session = get_active_session()
    session_id = active_session['id']
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


def analyser_confrontations_directes(equipe_dom_id, equipe_ext_id):
    """Analyse H2H (Helper DB)."""
    active_session = get_active_session()
    session_id = active_session['id']
    try:
        with get_db_connection() as conn:
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
    except: return 0


def obtenir_predictions_zeus_journee(journee: int) -> List[Dict]:
    """
    Récupère les décisions de ZEUS pour tous les matchs d'une journée.
    Prend en compte le capital actuel de la session active.
    """
    _reload_config()
    
    # 0. Vérif Sommeil Profond
    if getattr(config, 'ZEUS_DEEP_SLEEP', False):
        return []

    # 1. Charger le modèle
    model = get_zeus_model()
    if not model:
        logger.warning("Modèle ZEUS non trouvé pour l'inférence.")
        return []

    active_session = get_active_session()
    session_id = active_session['id']
    
    predictions = []
    try:
        with get_db_connection() as conn:
            # 2. Récupérer les matchs de la journée pour la session active
            matches = get_matches_for_journee(journee, conn)
            
            # 3. Récupérer capital actuel pour la session active
            cursor = conn.cursor()
            cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = ? ORDER BY id_pari DESC LIMIT 1", (session_id,))
            row = cursor.fetchone()
            capital_actuel = row[0] if row else active_session['capital_initial']
            
            for m in matches:
                # ZEUS prédit même si cotes absentes (fallback géré dans construire_observation)
                if not m['cote_1'] or not m['cote_x'] or not m['cote_2']:
                    continue
                    
                action_id, details = predire_pari_zeus(model, m, conn)
                
                # Calcul de la mise en Ar
                mise_ar = int(capital_actuel * details['pourcentage'])
                if mise_ar < 1000 and details['type'] != 'Aucun':
                    # Si mise trop faible mais ZEUS veut parier, on l'affiche quand même mais on note 0
                    mise_ar = 0
                
                predictions.append({
                    'match_id': m['id'],
                    'equipe_dom': m['equipe_dom_nom'],
                    'equipe_ext': m['equipe_ext_nom'],
                    'action_id': action_id,
                    'pari_type': details['type'],
                    'mise_ar': mise_ar,
                    'pourcentage': details['pourcentage'],
                    'decision_formatee': formater_decision_zeus(details)
                })
                
    except Exception as e:
        logger.error(f"Erreur prédictions ZEUS J{journee} : {e}")
        
    return predictions


def mettre_a_jour_scoring():
    """Valide les prédictions passées via IDs pour la session active."""
    active_session = get_active_session()
    session_id = active_session['id']
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT id, match_id, prediction FROM predictions WHERE session_id = ? AND succes IS NULL", (session_id,))
            en_attente = cursor.fetchall()
            
            for p in en_attente:
                pid, match_id, pred = p
                
                cursor.execute('''
                    SELECT score_dom, score_ext FROM matches 
                    WHERE id = ?
                ''', (match_id,))
                res = cursor.fetchone()
                
                if res:
                    sd, se = res
                    # Vérifier que les scores ne sont pas None
                    if sd is None or se is None:
                        continue
                        
                    resultat_reel = "1" if sd > se else ("2" if se > sd else "X")
                    succes = 1 if resultat_reel == pred else 0
                    
                    # Mise à jour de la prédiction
                    cursor.execute('''
                        UPDATE predictions 
                        SET resultat = ?, succes = ?
                        WHERE id = ?
                    ''', (resultat_reel, succes, pid))

                    # Mise à jour du score PRISMA de la session
                    pts = config.PRISMA_POINTS_VICTOIRE if succes == 1 else config.PRISMA_POINTS_DEFAITE
                    cursor.execute('''
                        UPDATE sessions 
                        SET score_prisma = score_prisma + ?
                        WHERE id = ?
                    ''', (pts, session_id))
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du scoring : {e}", exc_info=True)
        print(f"❌ Erreur lors de la mise à jour du scoring : {e}")
        return
    
    print("Mise a jour du scoring terminee.")

if __name__ == "__main__":
    print("Lancez via main.py")
