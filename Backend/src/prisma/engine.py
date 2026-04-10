from prisma.audit import analyzers
import logging

logger = logging.getLogger(__name__)

def calculer_score_prisma(data):
    """
    Scoring PRISMA classique (logiciel métier original).
    """
    # Convertir les points en nombres si ce sont des chaînes
    pts_dom = float(data["pts_dom"]) if isinstance(data["pts_dom"], str) else data["pts_dom"]
    pts_ext = float(data["pts_ext"]) if isinstance(data["pts_ext"], str) else data["pts_ext"]

    score_classement = (pts_dom - pts_ext) * 0.4
    
    forme_dom_str = data.get("forme_dom", "")
    forme_ext_str = data.get("forme_ext", "")
    
    f_dom_score = analyzers.pondere_forme_prisma(forme_dom_str)
    f_ext_score = analyzers.pondere_forme_prisma(forme_ext_str)
    score_forme = (f_dom_score - f_ext_score) * 0.3

    score_buts = 0
    if all(k in data for k in ["bp_dom", "bc_dom", "bp_ext", "bc_ext"]):
        diff_attaque = (data["bp_dom"] - data["bp_ext"]) * 0.1
        diff_defense = (data["bc_ext"] - data["bc_dom"]) * 0.1
        score_buts = (diff_attaque + diff_defense) * 0.15

    avantage_domicile = 2.0
    score_base = score_classement + score_forme + score_buts + avantage_domicile

    # Vérification des rejets
    if analyzers.detecter_instabilite_prisma(forme_dom_str) or \
       analyzers.detecter_instabilite_prisma(forme_ext_str):
        return None, "REJET_INSTABILITE"

    if analyzers.detecter_match_equilibre_prisma(data.get("cote_1"), data.get("cote_x"), data.get("cote_2")):
        return None, "REJET_EQUILIBRE"

    bonus_cotes = analyzers.analyser_cotes_suspectes_prisma(data.get("cote_1"), data.get("cote_x"), data.get("cote_2"))
    if bonus_cotes <= -3.0:
        return None, "REJET_PIEGE_COTES"

    bonus_h2h = data.get("bonus_h2h", 0)
    if bonus_h2h <= -2.5:
        return None, "REJET_H2H_DEFAVORABLE"

    momentum_dom = analyzers.calculer_momentum_prisma(forme_dom_str)
    momentum_ext = analyzers.calculer_momentum_prisma(forme_ext_str)
    bonus_momentum = (momentum_dom - momentum_ext) * 0.5

    score_final = score_base + bonus_h2h + bonus_cotes + bonus_momentum

    SEUIL_VICTOIRE = 7.0
    SEUIL_NUL_MAX = 3.0
    SEUIL_NUL_MIN = -3.0

    if score_final > SEUIL_VICTOIRE:
        return "1", score_final
    elif score_final < -SEUIL_VICTOIRE:
        return "2", abs(score_final)
    elif SEUIL_NUL_MIN <= score_final <= SEUIL_NUL_MAX:
        return "X", abs(score_final)

    return None, "ZONE_INCERTITUDE"


def calculer_score_prisma_v2(data, conn=None):
    """
    Version hybride : PRISMA classique + Ensemble ML (XGBoost + CatBoost).
    L'Ensemble est utilisé si activé par l'utilisateur dans l'interface.
    """
    from src.core.system import config
    from src.core.db.database import get_db_connection
    
    # 1. Obtenir le résultat classique pour les filtres de rejet et le fallback
    classic_res, classic_score = calculer_score_prisma(data)
    
    # Si rejet strict par le métier, on s'arrête là (sécurité bankroll)
    if classic_res is None and str(classic_score).startswith("REJET"):
        return None, classic_score, {}

    # 2. Vérifier si l'Ensemble ML est activé (dynamiquement via DB)
    ensemble_enabled = getattr(config, 'PRISMA_XGBOOST_ENABLED', False)
    try:
        with get_db_connection() as conn_check:
            with conn_check.cursor() as cur:
                cur.execute("SELECT value_int FROM prisma_config WHERE key = 'ensemble_enabled'")
                row = cur.fetchone()
                if row:
                    ensemble_enabled = bool(row["value_int"])
    except Exception as e:
        logger.warning(f"[ENGINE] Erreur check ensemble toggle: {e}")

    # 2. Tentative de prédiction via Ensemble ML
    if ensemble_enabled:
        try:
            from prisma.models import ensemble
            # Utiliser la connexion déjà importée
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1")
                session_row = cursor.fetchone()
                if session_row:
                    data['session_id'] = session_row['id']
                ml_result = ensemble.predict_ensemble(data)
            
            if ml_result:
                # --- Phase: Score Unifié et Validation Poisson ---
                poisson_enabled = getattr(config, 'PRISMA_POISSON_ENABLED', False)
                poisson_agrees = False
                
                if poisson_enabled:
                    try:
                        from prisma.models import poisson
                        from src.core.system.session_manager import get_active_session
                        
                        with get_db_connection() as local_conn:
                            session = get_active_session(local_conn)
                            p_res = poisson.predict_score_probs(
                                data['equipe_dom_id'], 
                                data['equipe_ext_id'], 
                                local_conn, 
                                session['id']
                            )
                                
                        if p_res:
                                ml_pred = ml_result['prediction']
                                poi_probs = p_res['probabilities']
                                poi_pred = max(poi_probs, key=poi_probs.get)
                                
                                logger.info(f"[POISSON] Pred: {p_res['most_likely_score']} ({poi_pred}) | λ {p_res['lambda_home']:.2f}-{p_res['lambda_away']:.2f}")
                                
                                ml_result['poisson'] = {
                                    'score': p_res['most_likely_score'],
                                    'prediction': poi_pred,
                                    'lambda_home': round(p_res['lambda_home'], 2),
                                    'lambda_away': round(p_res['lambda_away'], 2),
                                    'probabilities': {k: round(float(v), 2) for k, v in poi_probs.items()}
                                }
                                
                                if ml_pred == poi_pred:
                                    poisson_agrees = True
                                    ml_result['source'] = f"{ml_result.get('source', 'ML')}+Poisson"
                    except Exception as p_err:
                        logger.warning(f"[ENGINE] Erreur Poisson validation: {p_err}")

                # --- 3. Score de Confiance Unifié ---
                blend_conf = ml_result.get('blend_confidence', ml_result.get('confidence', 0.5))
                divergence = ml_result.get('divergence', 0.0)
                
                final_score = blend_conf
                final_score -= divergence * 0.5                     # Malus divergence
                final_score += 0.05 if poisson_agrees else -0.05    # Bonus/Malus si Poisson
                
                final_score = max(0.0, min(1.0, final_score))
                ml_result['confidence'] = final_score

                # --- 4. Règle du Silence Intelligent ---
                is_defensive = getattr(config, 'PREDICTION_DEFENSIVE_MODE', False)
                threshold = 0.70 if is_defensive else 0.55
                
                refus_auto = [
                    divergence > 0.35,           # Modèles trop en désaccord
                    final_score < threshold,     # Confiance unifiée trop faible
                    blend_conf < 0.50,           # Aucune issue clairement dominante
                    poisson_enabled and not poisson_agrees # Poisson contredit le blend
                ]
                
                if any(refus_auto):
                    # On stocke pourquoi on a refusé
                    ml_result['silence_intelligent'] = {
                        'threshold_used': threshold,
                        'final_score': round(final_score, 3),
                        'divergence': round(divergence, 3),
                        'poisson_agrees': poisson_agrees,
                        'is_defensive': is_defensive,
                        'reason': 'Silence Intelligent déclenché'
                    }
                    logger.info(f"[ENGINE] Silence Intelligent: Div={divergence:.2f}, Score={final_score:.2f}, Acc={poisson_agrees} -> NO_BET")
                    return 'NO_BET', 0.0, ml_result

                # Retourner le résultat ML unifié
                return ml_result['prediction'], ml_result['confidence'], ml_result
        except Exception as ml_err:
            logger.error(f"[ENGINE] Erreur Ensemble ML: {ml_err}")

    # 4. Fallback vers PRISMA classique si ML désactivé ou échec
    return classic_res, classic_score, {}
