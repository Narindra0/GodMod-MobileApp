"""
PRISMA LightGBM — Model Management Module
Entraînement, chargement, prédiction du modèle LightGBM.
LightGBM offre une excellente performance sur données tabulaires avec rapidité.
Complète le trio XGBoost + CatBoost pour l'ensemble learning.
"""

import os
import sys
import json
import logging
import numpy as np
from datetime import datetime

from prisma import xgboost_features

logger = logging.getLogger(__name__)

# État du modèle en mémoire (singleton)
_model = None
_model_metadata = None


def _get_model_dir():
    """Retourne le répertoire de stockage du modèle avec détection robuste."""
    # 1. Tenter via core.config pour la cohérence globale
    try:
        try:
            from src.core.system import config
        except ImportError:
            # Tenter avec un path local si on est dans un sous-répertoire
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from src.core.system import config
        
        if hasattr(config, 'BASE_DIR'):
            path = os.path.join(config.BASE_DIR, 'models', 'prisma')
            if os.path.exists(path):
                return path
    except Exception:
        pass
    
    # 2. Fallback robuste : basé sur la position physique de ce fichier
    this_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_path = os.path.abspath(os.path.join(this_dir, '..', '..', 'models', 'prisma'))
    return fallback_path


def _get_model_path():
    return os.path.join(_get_model_dir(), 'lightgbm_model.txt')


def _get_metadata_path():
    return os.path.join(_get_model_dir(), 'lightgbm_metadata.json')


def is_model_ready() -> bool:
    """Vérifie si un modèle entraîné existe sur le disque."""
    return os.path.exists(_get_model_path())


def load_model():
    """Charge le modèle LightGBM depuis le disque en mémoire."""
    global _model, _model_metadata
    
    if _model is not None:
        return _model
    
    model_path = _get_model_path()
    if not os.path.exists(model_path):
        logger.info(f"[LIGHTGBM] Aucun modèle trouvé à: {model_path}")
        return None
    
    try:
        import lightgbm as lgb
        _model = lgb.Booster(model_file=model_path)
        
        meta_path = _get_metadata_path()
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                _model_metadata = json.load(f)
        
        logger.info(f"[LIGHTGBM] Modèle chargé avec succès. Metadata: {_model_metadata}")
        return _model
    except ImportError:
        logger.warning("[LIGHTGBM] Bibliothèque 'lightgbm' non installée. pip install lightgbm")
        return None
    except Exception as e:
        logger.error(f"[LIGHTGBM] Erreur chargement modèle: {e}", exc_info=True)
        return None


def train_model(conn, force=False, decision=None):
    """Entraîne le modèle LightGBM avec complexité adaptative et triggers avancés."""
    global _model, _model_metadata
    from src.core.system import config

    try:
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score, StratifiedKFold
    except ImportError:
        logger.warning("[LIGHTGBM] Bibliothèques requises manquantes. pip install lightgbm scikit-learn")
        return False

    # Importer les modules avancés
    from prisma.training.session_weighted_training import extract_weighted_training_data, get_training_summary
    from prisma.strategy.adaptive_complexity import get_training_context, log_complexity_summary
    
    # Récupérer le contexte d'entraînement
    from src.core.system.session_manager import get_active_session
    current_session = get_active_session(conn)
    if not current_session:
        logger.warning("[LIGHTGBM] Impossible de déterminer la session actuelle")
        return False
    
    current_session_id = current_session['id']
    current_day = current_session.get('current_day', 1)
    
    # Utiliser la décision fournie ou évaluer les triggers si nécessaire
    if decision is None:
        from prisma.training.training_triggers import should_retrain_models
        decisions = should_retrain_models(conn, current_session_id, current_day)
        lgb_decision = decisions.get('lightgbm', decisions.get('xgboost', {}))
        # Si lightgbm n'existe pas dans decisions, utiliser xgboost comme fallback
        if not lgb_decision:
            lgb_decision = {'should_train': True, 'primary_reason': 'new_model_initialization'}
    else:
        lgb_decision = decision
    
    if not force and not lgb_decision.get('should_train', True):
        logger.info(f"[LIGHTGBM] Pas de réentraînement nécessaire: {lgb_decision.get('primary_reason', 'unknown')}")
        return False
    
    # Logger la décision
    from prisma.training.training_triggers import TrainingTrigger
    trigger_manager = TrainingTrigger(conn)
    trigger_manager.log_training_decision(lgb_decision)
    
    # Récupérer le contexte de complexité adaptative
    context = get_training_context(conn, current_session_id)
    log_complexity_summary(context)
    
    # Extraire les données pondérées
    X, y = extract_weighted_training_data(conn, current_session_id, min_matches=200)
    if X is None or len(y) < 200:
        actual = 0 if y is None else len(y)
        logger.info(f"[LIGHTGBM] Pas assez de données pondérées ({actual}/200).")
        return False
    
    # FORÇAGE TEMPORAIRE: Si le modèle existant a 31 features, on doit ré-entraîner pour passer à 57
    if not force:
        model_meta = get_model_info()
        if model_meta and model_meta.get('features_count', 0) == 31:
            logger.info("[LIGHTGBM] 🔄 Détection d'un ancien modèle (31 features). Forçage du ré-entraînement vers 57 features...")
            force = True
    
    # LightGBM ne supporte pas les chaînes. On garde seulement les features numériques.
    if hasattr(X, 'iloc'):
        # XGBoost utilise 55 features numériques (57 totales - 2 strings)
        # On utilise la même logique : exclure forme_raw_dom et forme_raw_ext
        feature_cols = [col for col in X.columns if col not in ['forme_raw_dom', 'forme_raw_ext']]
        X_numeric = X[feature_cols].values.astype('float32')
    else:
        X_numeric = X.astype('float32')
    
    from prisma.training.training_status import status_manager
    status_manager.update_model("lightgbm", status="training", progress=10)
    logger.info(f"[LIGHTGBM] Début de l'entraînement adaptatif sur {len(y)} échantillons...")
    logger.info(f"[LIGHTGBM] Features utilisées: {X_numeric.shape[1]}")
    
    # Configuration LightGBM adaptative basée sur la phase
    phase = context.get('phase', 'mid')
    
    # Paramètres LightGBM par phase (similaire à XGBoost mais adapté)
    lgb_configs = {
        'early': {
            'num_leaves': 70,
            'max_depth': 8,
            'learning_rate': 0.03,
            'n_estimators': 300,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 0.01,
            'reg_lambda': 1.0,
            'min_child_samples': 5
        },
        'mid': {
            'num_leaves': 50,
            'max_depth': 7,
            'learning_rate': 0.05,
            'n_estimators': 250,
            'subsample': 0.85,
            'colsample_bytree': 0.85,
            'reg_alpha': 0.05,
            'reg_lambda': 1.5,
            'min_child_samples': 10
        },
        'late': {
            'num_leaves': 35,
            'max_depth': 6,
            'learning_rate': 0.07,
            'n_estimators': 200,
            'subsample': 0.9,
            'colsample_bytree': 0.9,
            'reg_alpha': 0.1,
            'reg_lambda': 2.0,
            'min_child_samples': 15
        },
        'end': {
            'num_leaves': 20,
            'max_depth': 5,
            'learning_rate': 0.1,
            'n_estimators': 150,
            'subsample': 0.95,
            'colsample_bytree': 0.95,
            'reg_alpha': 0.2,
            'reg_lambda': 3.0,
            'min_child_samples': 20
        }
    }
    
    lgb_config = lgb_configs.get(phase, lgb_configs['mid'])
    
    # Créer le dataset LightGBM
    train_data = lgb.Dataset(X_numeric, label=y)
    
    # Paramètres pour l'entraînement
    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': lgb_config['num_leaves'],
        'max_depth': lgb_config['max_depth'],
        'learning_rate': lgb_config['learning_rate'],
        'subsample': lgb_config['subsample'],
        'colsample_bytree': lgb_config['colsample_bytree'],
        'reg_alpha': lgb_config['reg_alpha'],
        'reg_lambda': lgb_config['reg_lambda'],
        'min_child_samples': lgb_config['min_child_samples'],
        'verbose': -1,
        'device': 'gpu',
        'random_state': 42
    }
    
    # Validation croisée avec stratification
    # Note: LightGBM 4.0+ utilise des callbacks au lieu d'arguments directs
    callbacks = [
        lgb.early_stopping(stopping_rounds=20),
        lgb.log_evaluation(period=0) # Équivalent à verbose_eval=False
    ]
    
    status_manager.update_model("lightgbm", status="training", progress=30)
    cv_results = lgb.cv(
        params,
        train_data,
        num_boost_round=lgb_config['n_estimators'],
        nfold=5,
        stratified=True,
        callbacks=callbacks
    )
    status_manager.update_model("lightgbm", status="training", progress=80)
    
    best_iteration = len(cv_results['valid multi_logloss-mean'])
    cv_logloss = cv_results['valid multi_logloss-mean'][-1]
    cv_std = cv_results['valid multi_logloss-stdv'][-1]
    
    # Convertir logloss en accuracy approximée (heuristique)
    cv_accuracy = max(0.3, 1.0 - cv_logloss / 2.0)
    
    status_manager.update_model("lightgbm", status="training", progress=90, accuracy=float(cv_accuracy))
    logger.info(f"[LIGHTGBM] CV LogLoss: {cv_logloss:.4f} (±{cv_std:.4f})")
    logger.info(f"[LIGHTGBM] Meilleure iteration: {best_iteration}")
    
    # Entraînement final
    model = lgb.train(
        params,
        train_data,
        num_boost_round=best_iteration
    )
    
    # Extraction des Feature Importances
    try:
        importance = model.feature_importance(importance_type='gain')
        feature_names = [col for col in xgboost_features.FEATURE_NAMES if col not in ['forme_raw_dom', 'forme_raw_ext']]
        
        feature_importance = {}
        total_gain = sum(importance) if sum(importance) > 0 else 1
        
        for i, imp in enumerate(importance):
            if i < len(feature_names):
                name = feature_names[i]
                feature_importance[name] = float((imp / total_gain) * 100)
                
    except Exception as e:
        logger.warning(f"[LIGHTGBM] Erreur extraction feature importance: {e}")
        feature_importance = {}
    
    # Métadonnées enrichies
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'features_count': X_numeric.shape[1],
        'training_samples': len(y),
        'cv_logloss': cv_logloss,
        'cv_std': cv_std,
        'cv_accuracy': cv_accuracy,
        'feature_names': feature_names if 'feature_names' in dir() else [],
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
            'phase': phase,
            'current_day': current_day,
            'config_used': lgb_config
        },
        'triggers': lgb_decision.get('triggers', []),
        'primary_trigger_reason': lgb_decision.get('primary_reason', 'unknown'),
        'best_iteration': best_iteration
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
        f"[LIGHTGBM] ✅ Modèle adaptatif sauvegardé. "
        f"Échantillons: {len(y)} | "
        f"Session: {current_session_id} | "
        f"Journée: {current_day} | "
        f"Phase: {phase} | "
        f"CV LogLoss: {cv_logloss:.4f} | "
        f"Trigger: {lgb_decision.get('primary_reason', 'unknown')}"
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
    from prisma import xgboost_features
    
    model = load_model()
    if model is None:
        return None
    
    try:
        # Conversion en DataFrame pour le traitement (mais 'features' est déjà numérique à 57 colonnes)
        import pandas as pd
        # Utiliser NUMERIC_FEATURE_NAMES car extract_features(as_dataframe=False) retourne 57 éléments
        X = pd.DataFrame(features.reshape(1, -1), columns=xgboost_features.NUMERIC_FEATURE_NAMES)
        
        # Probabilités brutes pour chaque classe
        raw_probas = model.predict(X)[0]
        
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
        logger.error(f"[LIGHTGBM] Erreur de prédiction: {e}", exc_info=True)
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
    
    return {'status': 'no_model', 'message': 'Aucun modèle LightGBM entraîné.'}


def invalidate_model():
    """Force le rechargement du modèle au prochain appel en le supprimant du disque."""
    global _model, _model_metadata
    _model = None
    _model_metadata = None
    try:
        model_p = _get_model_path()
        if os.path.exists(model_p):
            os.remove(model_p)
    except Exception as e:
        logger.error(f"[LIGHTGBM] Erreur suppression disque: {e}")
    logger.info("[LIGHTGBM] Cache modèle invalidé et supprimé du disque.")
