"""
PRISMA CatBoost — Model Management Module
Entraînement, chargement, prédiction du modèle CatBoost.
CatBoost excelle sur les features catégorielles (forme, instabilité).
"""
import logging
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

_model = None
_model_metadata = None


def _get_model_dir():
    from ..core import config
    return os.path.join(config.BASE_DIR, 'models', 'prisma')


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

    if not os.path.exists(_get_model_path()):
        logger.info("[CATBOOST] Aucun modèle trouvé sur le disque.")
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


def train_model(conn, force=False):
    global _model, _model_metadata
    from ..core import config

    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError:
        logger.warning("[CATBOOST] pip install catboost requis.")
        return False

    from . import xgboost_features

    min_matches = getattr(config, 'PRISMA_XGBOOST_MIN_MATCHES', 100)

    X, y = xgboost_features.extract_training_data(conn)
    if X is None or len(y) < min_matches:
        actual = 0 if y is None else len(y)
        logger.info(f"[CATBOOST] Pas assez de données ({actual}/{min_matches}).")
        return False

    if not force and _model_metadata:
        last_count = _model_metadata.get('training_samples', 0)
        if len(y) - last_count < 20:
            logger.info("[CATBOOST] Pas assez de nouvelles données. Skip.")
            return False

    logger.info(f"[CATBOOST] Entraînement sur {len(y)} matchs...")

    # On utilise les noms de colonnes pour CatBoost
    cat_features = ['forme_raw_dom', 'forme_raw_ext']

    model = CatBoostClassifier(
        iterations=150,
        depth=6,
        learning_rate=0.05,
        loss_function='MultiClass',
        classes_count=3,
        random_seed=42,
        verbose=50,
        l2_leaf_reg=3,
        border_count=128,
        auto_class_weights='Balanced',
    )

    model.fit(X, y, cat_features=cat_features)

    # Sauvegarde
    model_dir = _get_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    model.save_model(_get_model_path())

    metadata = {
        'trained_at': datetime.now().isoformat(),
        'training_samples': len(y),
        'feature_names': xgboost_features.FEATURE_NAMES,
        'label_distribution': {
            '1': int((y == 0).sum()),
            'X': int((y == 1).sum()),
            '2': int((y == 2).sum()),
        },
    }
    with open(_get_metadata_path(), 'w') as f:
        json.dump(metadata, f, indent=2)

    _model = model
    _model_metadata = metadata

    logger.info(
        f"[CATBOOST] Modèle sauvegardé. Échantillons: {len(y)} | "
        f"Distribution: 1={metadata['label_distribution']['1']}, "
        f"X={metadata['label_distribution']['X']}, "
        f"2={metadata['label_distribution']['2']}"
    )
    return True


def predict_match(features) -> dict:
    from . import xgboost_features
    import pandas as pd

    model = load_model()
    if model is None:
        return None

    try:
        # Si c'est un DataFrame (1 ligne), on l'utilise direct
        # Sinon on reshape (numpy)
        if isinstance(features, pd.DataFrame):
            X = features
        else:
            X = features.reshape(1, -1)

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
    global _model, _model_metadata
    _model = None
    _model_metadata = None
    logger.info("[CATBOOST] Cache modèle invalidé.")
