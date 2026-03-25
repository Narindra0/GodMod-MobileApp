import logging
import numpy as np
import time

logger = logging.getLogger(__name__)


def predict_ensemble(data: dict) -> dict:
    """
    Combine XGBoost + CatBoost en extrayant les features adaptées à chaque modèle.
    """
    from ..core import config
    from . import xgboost_model, catboost_model, xgboost_features

    # Extraction duale avec connexion pour features avancées
    from ..core.database import get_db_connection
    
    with get_db_connection() as conn:
        features_xgb = xgboost_features.extract_features(data, as_dataframe=False, conn=conn)
        features_cat = xgboost_features.extract_features(data, as_dataframe=True, conn=conn)

    xgb_result = None
    cat_result = None

    # Tentative XGBoost
    try:
        if xgboost_model.is_model_ready():
            xgb_result = xgboost_model.predict_match(features_xgb)
    except Exception as e:
        logger.warning(f"[ENSEMBLE] XGBoost erreur: {e}")

    # Tentative CatBoost
    try:
        if catboost_model.is_model_ready():
            cat_result = catboost_model.predict_match(features_cat)
    except Exception as e:
        logger.warning(f"[ENSEMBLE] CatBoost erreur: {e}")

    # Aucun modèle disponible
    if xgb_result is None and cat_result is None:
        return None

    # Un seul modèle disponible → utiliser directement
    if xgb_result is None:
        cat_result['source'] = 'CatBoost_solo'
        return cat_result
    if cat_result is None:
        xgb_result['source'] = 'XGBoost_solo'
        return xgb_result

    # Les deux modèles disponibles → Weighted averaging
    xgb_weight = getattr(config, 'ENSEMBLE_XGBOOST_WEIGHT', 0.5)
    
    # 1. Blend Dynamique (basé sur cv_accuracy)
    xgb_info = xgboost_model.get_model_info()
    cat_info = catboost_model.get_model_info()
    
    xgb_acc = xgb_info.get('cv_accuracy', 0) if isinstance(xgb_info, dict) else 0
    cat_acc = cat_info.get('cv_accuracy', 0) if isinstance(cat_info, dict) else 0
    
    if xgb_acc > 0 and cat_acc > 0:
        total_acc = xgb_acc + cat_acc
        xgb_weight = xgb_acc / total_acc
    
    cat_weight = 1.0 - xgb_weight

    xgb_p = xgb_result['probabilities']
    cat_p = cat_result['probabilities']

    # Moyenne pondérée des probabilités par classe
    blend_probs = {
        '1': xgb_p['1'] * xgb_weight + cat_p['1'] * cat_weight,
        'X': xgb_p['X'] * xgb_weight + cat_p['X'] * cat_weight,
        '2': xgb_p['2'] * xgb_weight + cat_p['2'] * cat_weight,
    }

    # Déterminer la classe gagnante
    best_class = max(blend_probs, key=blend_probs.get)
    blend_confidence = blend_probs[best_class]
    confidence = blend_confidence
    
    # 2. Malus de Divergence
    xgb_top_prob = max(xgb_p.values())
    cat_top_prob = max(cat_p.values())
    divergence = abs(xgb_top_prob - cat_top_prob)
    
    if divergence > 0.30:
        confidence *= 0.60
    elif divergence > 0.20:
        confidence *= 0.80

    # Log de diagnostic
    accord = xgb_result['prediction'] == cat_result['prediction']
    logger.info(
        f"[ENSEMBLE] XGB={xgb_result['prediction']}({max(xgb_p.values()):.2%} w:{xgb_weight:.2f}) "
        f"CAT={cat_result['prediction']}({max(cat_p.values()):.2%} w:{cat_weight:.2f}) "
        f"→ Blend={best_class}({blend_confidence:.2%} -> Final: {confidence:.2%}) | "
        f"Div={divergence:.2f} | {'✓ ACCORD' if accord else '⚠ DÉSACCORD'}"
    )

    return {
        'prediction': best_class,
        'confidence': confidence,
        'blend_confidence': blend_confidence,
        'divergence': divergence,
        'probabilities': blend_probs,
        'source': 'Ensemble_XGB+CAT',
        'agreement': accord,
        'models': {
            'xgboost': {'prediction': xgb_result['prediction'], 'probabilities': xgb_p, 'weight': xgb_weight},
            'catboost': {'prediction': cat_result['prediction'], 'probabilities': cat_p, 'weight': cat_weight}
        }
    }


def train_ensemble(conn, force=False):
    """Entraîne les deux modèles avec triggers intelligents et complexité adaptative."""
    from . import xgboost_model, catboost_model
    
    logger.info("[ENSEMBLE] 🚀 DÉMARRAGE ENTRAÎNEMENT ADAPTATIF AVANCÉ")
    start_time = time.time()
    
    # Récupérer le contexte actuel
    from src.core.session_manager import get_active_session
    current_session = get_active_session(conn)
    if not current_session:
        logger.error("[ENSEMBLE] Impossible de déterminer la session actuelle")
        return False
    
    current_session_id = current_session['id']
    current_day = current_session.get('current_day', 1)
    
    logger.info(f"[ENSEMBLE] Contexte: Session {current_session_id}, Journée {current_day}")
    
    # Évaluer les triggers pour tous les modèles
    from .training_triggers import should_retrain_models, get_training_summary
    
    try:
        decisions = should_retrain_models(conn, current_session_id, current_day)
    except Exception as e:
        logger.error(f"[ENSEMBLE] Erreur évaluation triggers: {e}")
        return False
    
    # Afficher le résumé des décisions
    try:
        summary = get_training_summary(decisions)
        logger.info(f"[ENSEMBLE] Résumé: {len(summary['models_to_train'])} modèles à entraîner, "
                    f"{summary['total_triggers']} triggers activés")
    except Exception as e:
        logger.error(f"[ENSEMBLE] Erreur génération résumé: {e}")
        # Utiliser un résumé par défaut
        summary = {'models_to_train': [], 'total_triggers': 0}
    
    # Entraîner les modèles nécessaires
    trained_models = []
    
    # XGBoost
    if decisions['xgboost']['should_train']:
        logger.info("[ENSEMBLE] 📊 Entraînement XGBoost adaptatif...")
        xgb_success = xgboost_model.train_model(conn, force, decisions['xgboost'])
        if xgb_success:
            trained_models.append('XGBoost')
            logger.info("[ENSEMBLE] ✅ XGBoost entraîné avec succès")
        else:
            logger.error("[ENSEMBLE] ❌ Échec entraînement XGBoost")
    else:
        logger.info(f"[ENSEMBLE] ⏸️ XGBoost sauté: {decisions['xgboost']['primary_reason']}")
    
    # CatBoost
    if decisions['catboost']['should_train']:
        logger.info("[ENSEMBLE] 🐈 Entraînement CatBoost adaptatif...")
        cat_success = catboost_model.train_model(conn, force, decisions['catboost'])
        if cat_success:
            trained_models.append('CatBoost')
            logger.info("[ENSEMBLE] ✅ CatBoost entraîné avec succès")
        else:
            logger.error("[ENSEMBLE] ❌ Échec entraînement CatBoost")
    else:
        logger.info(f"[ENSEMBLE] ⏸️ CatBoost sauté: {decisions['catboost']['primary_reason']}")
    
    # Bilan final
    if trained_models:
        logger.info(f"[ENSEMBLE] 🎉 ENTRAÎNEMENT TERMINÉ: {', '.join(trained_models)}")
        
        # Afficher les métadonnées finales
        for model_name in trained_models:
            if model_name == 'XGBoost':
                metadata = xgboost_model.get_model_metadata()
            elif model_name == 'CatBoost':
                metadata = catboost_model.get_model_metadata()
            
            if metadata:
                cv_acc = metadata.get('cv_accuracy', 0)
                phase = metadata.get('complexity_context', {}).get('phase', 'unknown')
                trigger = metadata.get('primary_trigger_reason', 'unknown')
                logger.info(f"[ENSEMBLE] {model_name}: CV={cv_acc:.4f}, Phase={phase}, Trigger={trigger}")
        
        # Log de durée totale
        end_time = time.time()
        duration = end_time - start_time
        logger.info(f"[ENSEMBLE] ⏱️ Durée totale: {duration:.2f} secondes")
        return True
    else:
        logger.info("[ENSEMBLE] ⏸️ AUCUN ENTRAÎNEMENT EFFECTUÉ - Tous les modèles à jour")
        return False


def get_ensemble_info() -> dict:
    """Retourne le statut des deux modèles pour l'UI/API."""
    from . import xgboost_model, catboost_model

    return {
        'xgboost': xgboost_model.get_model_info(),
        'catboost': catboost_model.get_model_info(),
        'ensemble_active': xgboost_model.is_model_ready() and catboost_model.is_model_ready(),
    }
