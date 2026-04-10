"""
PRISMA CatBoost — Model Management Module
Entraînement, chargement, prédiction du modèle CatBoost.
CatBoost excelle sur les features catégorielles (forme, instabilité).
"""
import os
import sys
import json
import logging
import numpy as np
from datetime import datetime

from prisma import xgboost_features

logger = logging.getLogger(__name__)

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
    return os.path.join(_get_model_dir(), 'catboost_model.cbm')


def _get_metadata_path():
    return os.path.join(_get_model_dir(), 'catboost_metadata.json')


def is_model_ready() -> bool:
    return os.path.exists(_get_model_path())


def load_model():
    global _model, _model_metadata

    if _model is not None:
        return _model
    
    model_path = _get_model_path()
    if not os.path.exists(model_path):
        logger.info(f"[CATBOOST] Aucun modèle trouvé à: {model_path}")
        return None

    try:
        from catboost import CatBoostClassifier
        _model = CatBoostClassifier()
        _model.load_model(_get_model_path())

        meta_path = _get_metadata_path()
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                _model_metadata = json.load(f)

        logger.info(f"[CATBOOST] Modèle chargé. Metadata: {_model_metadata}")
        return _model
    except ImportError:
        logger.warning("[CATBOOST] Bibliothèque 'catboost' non installée. pip install catboost")
        return None
    except Exception as e:
        logger.error(f"[CATBOOST] Erreur chargement: {e}", exc_info=True)
        return None


def train_model(conn, force=False, decision=None):
    """Entraîne le modèle CatBoost avec complexité adaptative et triggers avancés."""
    global _model, _model_metadata
    from src.core.system import config

    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError:
        logger.warning("[CATBOOST] pip install catboost requis.")
        return False

    # Importer les modules avancés
    from prisma.training.session_weighted_training import extract_weighted_training_data, get_training_summary
    from prisma.strategy.adaptive_complexity import get_training_context, log_complexity_summary
    
    # Récupérer le contexte d'entraînement
    from src.core.system.session_manager import get_active_session
    current_session = get_active_session(conn)
    if not current_session:
        logger.warning("[CATBOOST] Impossible de déterminer la session actuelle")
        return False
    
    current_session_id = current_session['id']
    current_day = current_session.get('current_day', 1)
    
    # Utiliser la décision fournie ou évaluer les triggers si nécessaire
    if decision is None:
        from prisma.training.training_triggers import should_retrain_models
        decisions = should_retrain_models(conn, current_session_id, current_day)
        cat_decision = decisions['catboost']
    else:
        cat_decision = decision
    
    if not force and not cat_decision['should_train']:
        logger.info(f"[CATBOOST] Pas de réentraînement nécessaire: {cat_decision['primary_reason']}")
        return False
    
    # Logger la décision
    from prisma.training.training_triggers import TrainingTrigger
    trigger_manager = TrainingTrigger(conn)
    trigger_manager.log_training_decision(cat_decision)
    
    # Récupérer le contexte de complexité adaptative
    context = get_training_context(conn, current_session_id)
    log_complexity_summary(context)
    
    # Extraire les données pondérées
    X, y = extract_weighted_training_data(conn, current_session_id, min_matches=150)
    if X is None or len(y) < 150:
        actual = 0 if y is None else len(y)
        logger.info(f"[CATBOOST] Pas assez de données pondérées ({actual}/150).")
        return False

    # FORÇAGE TEMPORAIRE: Si le modèle existant a 31 features, on doit ré-entraîner pour passer à 59
    if not force:
        model_meta = get_model_info()
        if model_meta and model_meta.get('features_count', 0) == 31:
            logger.info("[CATBOOST] 🔄 Détection d'un ancien modèle (31 features). Forçage du ré-entraînement vers 59 features...")
            force = True

    from prisma.training.training_status import status_manager
    status_manager.update_model("catboost", status="training", progress=10)
    logger.info(f"[CATBOOST] Entraînement adaptatif sur {len(y)} échantillons...")

    # Configuration CatBoost adaptative
    cat_config = context['catboost_config']
    
    # On utilise les noms de colonnes pour CatBoost
    cat_features = ['forme_raw_dom', 'forme_raw_ext']

    model = CatBoostClassifier(
        iterations=cat_config['iterations'],
        depth=cat_config['depth'],
        learning_rate=cat_config['learning_rate'],
        loss_function='MultiClass',
        classes_count=3,
        random_seed=42,
        verbose=50,
        l2_leaf_reg=cat_config['l2_leaf_reg'],
        border_count=cat_config['border_count'],
        random_strength=cat_config['random_strength'],
        auto_class_weights='Balanced',
        task_type='GPU',
        devices='0'
    )

    status_manager.update_model("catboost", status="training", progress=30)
    model.fit(X, y, cat_features=cat_features)
    status_manager.update_model("catboost", status="completed", progress=100)

    # Métadonnées
    _model_metadata = {
        'trained_at': datetime.now().isoformat(),
        'features_count': X.shape[1],
        'training_samples': len(y),
        'feature_names': xgboost_features.FEATURE_NAMES,
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
            'config_used': cat_config
        },
        'triggers': cat_decision['triggers'],
        'primary_trigger_reason': cat_decision['primary_reason']
    }
    
    # Sauvegarde
    model_dir = _get_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    model.save_model(_get_model_path())

    with open(_get_metadata_path(), 'w') as f:
        json.dump(_model_metadata, f, indent=2)

    _model = model

    logger.info(
        f"[CATBOOST] ✅ Modèle adaptatif sauvegardé. "
        f"Échantillons: {len(y)} | "
        f"Session: {current_session_id} | "
        f"Journée: {current_day} | "
        f"Phase: {context['phase']} | "
        f"Trigger: {cat_decision['primary_reason']}"
    )
    return True


def predict_match(features) -> dict:
    from prisma import xgboost_features
    import pandas as pd

    model = load_model()
    if model is None:
        return None

    try:
        # Si c'est un DataFrame (1 ligne), on l'utilise direct
        # Sinon on reshape (numpy)
        # CatBoost préfère les DataFrame avec noms de colonnes pour la cohérence
        if isinstance(features, pd.DataFrame):
            X = features
        else:
            X = pd.DataFrame(features.reshape(1, -1), columns=xgboost_features.FEATURE_NAMES)

        probas = model.predict_proba(X)[0]
        predicted_class = int(probas.argmax())
        prediction = xgboost_features.LABEL_MAP_INV[predicted_class]

        return {
            'prediction': prediction,
            'confidence': float(probas[predicted_class]),
            'probabilities': {
                '1': float(probas[0]),
                'X': float(probas[1]),
                '2': float(probas[2]),
            }
        }
    except Exception as e:
        logger.error(f"[CATBOOST] Erreur prédiction: {e}", exc_info=True)
        return None


def get_model_metadata():
    """Retourne les métadonnées du modèle chargé."""
    return _model_metadata.copy() if _model_metadata else {}


def get_model_info() -> dict:
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
    return {'status': 'no_model'}


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
        logger.error(f"[CATBOOST] Erreur suppression disque: {e}")
    logger.info("[CATBOOST] Cache modèle invalidé et supprimé du disque.")
