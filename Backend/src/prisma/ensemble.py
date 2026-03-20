import logging
import numpy as np

logger = logging.getLogger(__name__)


def predict_ensemble(data: dict) -> dict:
    """
    Combine XGBoost + CatBoost en extrayant les features adaptées à chaque modèle.
    """
    from ..core import config
    from . import xgboost_model, catboost_model, xgboost_features

    # Extraction duale
    features_xgb = xgboost_features.extract_features(data, as_dataframe=False)
    features_cat = xgboost_features.extract_features(data, as_dataframe=True)

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
    confidence = blend_probs[best_class]

    # Log de diagnostic
    accord = xgb_result['prediction'] == cat_result['prediction']
    logger.info(
        f"[ENSEMBLE] XGB={xgb_result['prediction']}({xgb_result['confidence']:.2%}) "
        f"CAT={cat_result['prediction']}({cat_result['confidence']:.2%}) "
        f"→ Blend={best_class}({confidence:.2%}) | "
        f"{'✓ ACCORD' if accord else '⚠ DÉSACCORD'}"
    )

    return {
        'prediction': best_class,
        'confidence': confidence,
        'probabilities': blend_probs,
        'source': 'Ensemble_XGB+CAT',
        'agreement': accord,
    }


def train_all_models(conn, force=False):
    """Entraîne les deux modèles en séquence."""
    from . import xgboost_model, catboost_model

    xgb_ok = False
    cat_ok = False

    try:
        xgb_ok = xgboost_model.train_model(conn, force=force)
    except Exception as e:
        logger.error(f"[ENSEMBLE] XGBoost training échoué: {e}")

    try:
        cat_ok = catboost_model.train_model(conn, force=force)
    except Exception as e:
        logger.error(f"[ENSEMBLE] CatBoost training échoué: {e}")

    if xgb_ok or cat_ok:
        logger.info(f"[ENSEMBLE] Entraînement terminé. XGBoost={'✓' if xgb_ok else '✗'} CatBoost={'✓' if cat_ok else '✗'}")

    return xgb_ok or cat_ok


def get_ensemble_info() -> dict:
    """Retourne le statut des deux modèles pour l'UI/API."""
    from . import xgboost_model, catboost_model

    return {
        'xgboost': xgboost_model.get_model_info(),
        'catboost': catboost_model.get_model_info(),
        'ensemble_active': xgboost_model.is_model_ready() and catboost_model.is_model_ready(),
    }
