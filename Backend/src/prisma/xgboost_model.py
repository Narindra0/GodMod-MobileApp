"""
PRISMA XGBoost — Model Management Module
Entraînement, chargement, prédiction et ré-entraînement automatique du modèle XGBoost.
"""
import logging
import os
import json
from datetime import datetime

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


def train_model(conn, force=False):
    """
    Entraîne le modèle XGBoost sur les données historiques.
    
    Args:
        conn: connexion DB active
        force: si True, ré-entraîne même si un modèle existe déjà
        
    Returns:
        bool: True si l'entraînement a réussi
    """
    global _model, _model_metadata
    from ..core import config
    
    try:
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score
    except ImportError:
        logger.warning("[XGBOOST] Bibliothèques requises manquantes. pip install xgboost scikit-learn")
        return False
    
    from . import xgboost_features
    
    min_matches = getattr(config, 'PRISMA_XGBOOST_MIN_MATCHES', 100)
    
    # Extraction des données
    X, y = xgboost_features.extract_training_data(conn)
    if X is None or len(y) < min_matches:
        actual = 0 if y is None else len(y)
        logger.info(f"[XGBOOST] Pas assez de données pour l'entraînement ({actual}/{min_matches}).")
        return False
    
    # XGBoost ne supporte pas les chaînes. On garde seulement les features numériques.
    if hasattr(X, 'iloc'):
        X = X.iloc[:, :-2].values.astype('float32')
    
    if not force and _model_metadata:
        last_count = _model_metadata.get('training_samples', 0)
        
        total_matches = len(y)
        new_samples = total_matches - last_count
        
        # Logique des 3 Phases
        # Phase 1: Bootstrap (< 50 matchs)
        if total_matches < 50:
            if last_count > 0:
                logger.info(f"[XGBOOST] Phase 1 (Bootstrap) : {total_matches} < 50 matchs. Attente.")
                return False
                
        # Phase 2: Apprentissage actif (< 300 matchs)
        elif total_matches < 300:
            if new_samples < 50:
                logger.info(f"[XGBOOST] Phase 2 (Actif) : Attente 50 nouveaux matchs (actuel: {new_samples}).")
                return False
                
        # Phase 3: Maturité (>= 300 matchs)
        else:
            if new_samples < 100:
                logger.info(f"[XGBOOST] Phase 3 (Maturité) : Attente 100 nouveaux matchs (actuel: {new_samples}).")
                return False

    # Focus de maturité : Priorité absolue aux 740 derniers matchs (74 dernières journées)
    if len(y) > 740:
        logger.info(f"[XGBOOST] Écrêtage historique : {len(y)} matchs, limitation aux 740 derniers.")
        X = X[-740:]
        y = y[-740:]
    
    logger.info(f"[XGBOOST] Début de l'entraînement sur {len(y)} matchs...")
    
    # Configuration XGBoost optimisée pour le football virtuel
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        objective='multi:softprob',
        num_class=3,
        eval_metric='mlogloss',
        use_label_encoder=False,
        random_state=42,
        verbosity=0,
    )
    
    # Validation croisée pour évaluer les performances
    try:
        cv_scores = cross_val_score(model, X, y, cv=min(5, len(y) // 10), scoring='accuracy')
        cv_accuracy = float(cv_scores.mean())
        logger.info(f"[XGBOOST] CV Accuracy: {cv_accuracy:.3f} (+/- {cv_scores.std():.3f})")
    except Exception as e:
        logger.warning(f"[XGBOOST] Cross-validation échouée: {e}. Entraînement direct.")
        cv_accuracy = 0.0
    
    # Entraînement final sur toutes les données
    model.fit(X, y)
    
    # Sauvegarde
    model_dir = _get_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    
    model.save_model(_get_model_path())
    
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'training_samples': len(y),
        'cv_accuracy': cv_accuracy,
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
        f"[XGBOOST] Modèle entraîné et sauvegardé. "
        f"Accuracy CV: {cv_accuracy:.1%} | Échantillons: {len(y)} | "
        f"Distribution: 1={metadata['label_distribution']['1']}, "
        f"X={metadata['label_distribution']['X']}, "
        f"2={metadata['label_distribution']['2']}"
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
