"""
PRISMA XGBoost — Model Management Module
Entraînement, chargement, prédiction et ré-entraînement automatique du modèle XGBoost.
"""
import os
import json
import logging
import numpy as np
from datetime import datetime

from . import xgboost_features

logger = logging.getLogger(__name__)

# État du modèle en mémoire (singleton)
_model = None
_model_metadata = None


def _get_model_dir():
    """Retourne le répertoire de stockage du modèle."""
    from ..core import config
    return os.path.join(config.BASE_DIR, 'models', 'prisma')


def _get_model_path():
    return os.path.join(_get_model_dir(), 'xgboost_model.json')


def _get_metadata_path():
    return os.path.join(_get_model_dir(), 'xgboost_metadata.json')


def is_model_ready() -> bool:
    """Vérifie si un modèle entraîné existe sur le disque."""
    return os.path.exists(_get_model_path())


def load_model():
    """Charge le modèle XGBoost depuis le disque en mémoire."""
    global _model, _model_metadata
    
    if _model is not None:
        return _model
    
    model_path = _get_model_path()
    if not os.path.exists(model_path):
        logger.info("[XGBOOST] Aucun modèle trouvé sur le disque.")
        return None
    
    try:
        import xgboost as xgb
        _model = xgb.XGBClassifier()
        _model.load_model(model_path)
        
        meta_path = _get_metadata_path()
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                _model_metadata = json.load(f)
        
        logger.info(f"[XGBOOST] Modèle chargé avec succès. Metadata: {_model_metadata}")
        return _model
    except ImportError:
        logger.warning("[XGBOOST] Bibliothèque 'xgboost' non installée. pip install xgboost")
        return None
    except Exception as e:
        logger.error(f"[XGBOOST] Erreur chargement modèle: {e}", exc_info=True)
        return None


def train_model(conn, force=False, decision=None):
    """Entraîne le modèle XGBoost avec complexité adaptative et triggers avancés."""
    global _model, _model_metadata
    from ..core import config

    try:
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score
    except ImportError:
        logger.warning("[XGBOOST] Bibliothèques requises manquantes. pip install xgboost scikit-learn")
        return False

    # Importer les modules avancés
    from .session_weighted_training import extract_weighted_training_data, get_training_summary
    from .adaptive_complexity import get_training_context, log_complexity_summary
    
    # Récupérer le contexte d'entraînement
    from src.core.session_manager import get_active_session
    current_session = get_active_session(conn)
    if not current_session:
        logger.warning("[XGBOOST] Impossible de déterminer la session actuelle")
        return False
    
    current_session_id = current_session['id']
    current_day = current_session.get('current_day', 1)
    
    # Utiliser la décision fournie ou évaluer les triggers si nécessaire
    if decision is None:
        from .training_triggers import should_retrain_models
        decisions = should_retrain_models(conn, current_session_id, current_day)
        xgb_decision = decisions['xgboost']
    else:
        xgb_decision = decision
    
    if not force and not xgb_decision['should_train']:
        logger.info(f"[XGBOOST] Pas de réentraînement nécessaire: {xgb_decision['primary_reason']}")
        return False
    
    # Logger la décision
    from .training_triggers import TrainingTrigger
    trigger_manager = TrainingTrigger(conn)
    trigger_manager.log_training_decision(xgb_decision)
    
    # Récupérer le contexte de complexité adaptative
    context = get_training_context(conn, current_session_id)
    log_complexity_summary(context)
    
    # Extraire les données pondérées
    X, y = extract_weighted_training_data(conn, current_session_id, min_matches=200)
    if X is None or len(y) < 200:
        actual = 0 if y is None else len(y)
        logger.info(f"[XGBOOST] Pas assez de données pondérées ({actual}/200).")
        return False
    
    # XGBoost ne supporte pas les chaînes. On garde seulement les features numériques.
    if hasattr(X, 'iloc'):
        X = X.iloc[:, :31].values.astype('float32')  # Garder seulement les 31 premières features
    
    logger.info(f"[XGBOOST] Début de l'entraînement adaptatif sur {len(y)} échantillons...")
    
    # Configuration XGBoost adaptative
    xgb_config = context['xgboost_config']
    
    model = xgb.XGBClassifier(
        n_estimators=xgb_config['n_estimators'],
        max_depth=xgb_config['max_depth'],
        learning_rate=xgb_config['learning_rate'],
        subsample=xgb_config['subsample'],
        colsample_bytree=xgb_config['colsample_bytree'],
        min_child_weight=xgb_config['min_child_weight'],
        gamma=xgb_config['gamma'],
        reg_alpha=xgb_config['reg_alpha'],
        reg_lambda=xgb_config['reg_lambda'],
        random_state=42,
        n_jobs=-1,
        eval_metric='mlogloss'
    )
    
    # Validation croisée
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    cv_accuracy = cv_scores.mean()
    cv_std = cv_scores.std()
    
    logger.info(f"[XGBOOST] CV Accuracy: {cv_accuracy:.4f} (+/- {cv_std:.4f})")
    
    # Entraînement final
    model.fit(X, y)
    
    # Extraction des Feature Importances (Gain)
    try:
        booster = model.get_booster()
        importance = booster.get_score(importance_type='gain')
        
        feature_importance = {}
        total_gain = sum(importance.values())
        
        for k, v in importance.items():
            idx = int(k.replace('f', ''))
            if idx < len(xgboost_features.FEATURE_NAMES) - 2:
                name = xgboost_features.FEATURE_NAMES[idx]
                # Normaliser en pourcentage
                feature_importance[name] = float((v / total_gain) * 100) if total_gain > 0 else 0.0
                
    except Exception as e:
        logger.warning(f"[XGBOOST] Erreur extraction feature importance: {e}")
        feature_importance = {}
    
    # Métadonnées enrichies
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'training_samples': len(y),
        'cv_accuracy': cv_accuracy,
        'cv_std': cv_std,
        'feature_names': xgboost_features.FEATURE_NAMES,
        'feature_importance': feature_importance,
        'label_distribution': {
            '1': int((y == 0).sum()),
            'X': int((y == 1).sum()),
            '2': int((y == 2).sum()),
        },
        'last_training_session': current_session_id,
        'last_training_day': current_day,
        'training_method': 'adaptive_session_weighted',
        'session_summary': get_training_summary(conn, current_session_id),
        'complexity_context': {
            'phase': context['phase'],
            'current_day': current_day,
            'config_used': xgb_config
        },
        'triggers': xgb_decision['triggers'],
        'primary_trigger_reason': xgb_decision['primary_reason']
    }
    
    # Sauvegarde
    model_dir = _get_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    model.save_model(_get_model_path())

    with open(_get_metadata_path(), 'w') as f:
        json.dump(metadata, f, indent=2)

    _model = model
    _model_metadata = metadata

    logger.info(
        f"[XGBOOST] ✅ Modèle adaptatif sauvegardé. "
        f"Échantillons: {len(y)} | "
        f"Session: {current_session_id} | "
        f"Journée: {current_day} | "
        f"Phase: {context['phase']} | "
        f"CV: {cv_accuracy:.4f} | "
        f"Trigger: {xgb_decision['primary_reason']}"
    )
    return True


def predict_match(features) -> dict:
    """
    Prédit le résultat d'un match à partir des features.
    
    Args:
        features: np.ndarray de features extraites via xgboost_features.extract_features()
        
    Returns:
        dict avec 'prediction' (str: '1'/'X'/'2'), 'confidence' (float), 
        'probabilities' (dict: {1: float, X: float, 2: float})
        ou None si le modèle n'est pas prêt.
    """
    from . import xgboost_features
    
    model = load_model()
    if model is None:
        return None
    
    try:
        # Reshape pour une prédiction unique
        X = features.reshape(1, -1)
        
        # Probabilités brutes pour chaque classe
        raw_probas = model.predict_proba(X)[0]
        
        # Calibration pour éviter la sur-confiance extrême (Cap à 85% max, Plancher à 5% min)
        import numpy as np
        probas = np.clip(raw_probas, 0.05, 0.85)
        probas = probas / probas.sum()
        
        predicted_class = int(probas.argmax())
        
        prediction = xgboost_features.LABEL_MAP_INV[predicted_class]
        confidence = float(probas[predicted_class])
        
        return {
            'prediction': prediction,
            'confidence': confidence,
            'probabilities': {
                '1': float(probas[0]),
                'X': float(probas[1]),
                '2': float(probas[2]),
            }
        }
    except Exception as e:
        logger.error(f"[XGBOOST] Erreur de prédiction: {e}", exc_info=True)
        return None


def get_model_metadata():
    """Retourne les métadonnées du modèle chargé."""
    return _model_metadata.copy() if _model_metadata else {}


def get_model_info() -> dict:
    """Retourne les métadonnées du modèle actuel (pour l'UI/API)."""
    global _model_metadata
    
    if _model_metadata:
        return _model_metadata
    meta_path = _get_metadata_path()
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r') as f:
                _model_metadata = json.load(f)
            return _model_metadata
        except Exception:
            pass
    
    return {'status': 'no_model', 'message': 'Aucun modèle XGBoost entraîné.'}


def invalidate_model():
    """Force le rechargement du modèle au prochain appel."""
    global _model, _model_metadata
    _model = None
    _model_metadata = None
    logger.info("[XGBOOST] Cache modèle invalidé.")
