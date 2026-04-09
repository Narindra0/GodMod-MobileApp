import logging
import numpy as np
import time
import sys
import os
from typing import Dict, List, Optional, Tuple
from sklearn.linear_model import LogisticRegression
import pickle

logger = logging.getLogger(__name__)

# Meta-learner pour le stacking (entraîné dynamiquement)
_meta_learner = None
_meta_learner_path = None

def _get_meta_learner_path():
    """Retourne le chemin du meta-learner sauvegardé."""
    try:
        from core import config
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from core import config
    return os.path.join(config.BASE_DIR, 'models', 'prisma', 'meta_learner.pkl')


def _load_meta_learner():
    """Charge le meta-learner si disponible."""
    global _meta_learner
    if _meta_learner is not None:
        return _meta_learner
    
    path = _get_meta_learner_path()
    if os.path.exists(path):
        try:
            with open(path, 'rb') as f:
                _meta_learner = pickle.load(f)
            logger.info("[ENSEMBLE] Meta-learner chargé")
            return _meta_learner
        except Exception as e:
            logger.warning(f"[ENSEMBLE] Erreur chargement meta-learner: {e}")
    return None


def _save_meta_learner(learner):
    """Sauvegarde le meta-learner entraîné."""
    global _meta_learner
    _meta_learner = learner
    path = _get_meta_learner_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'wb') as f:
            pickle.dump(learner, f)
        logger.info("[ENSEMBLE] Meta-learner sauvegardé")
    except Exception as e:
        logger.warning(f"[ENSEMBLE] Erreur sauvegarde meta-learner: {e}")


def predict_ensemble(data: dict, use_stacking: bool = True) -> dict:
    """
    Combine XGBoost + CatBoost + LightGBM avec stacking ou blending.
    
    Args:
        data: Données du match
        use_stacking: Si True, utilise le meta-learner. Sinon, blending simple.
    """
    # Import dynamique de get_db_connection et xgboost_features
    # Import dynamique des modules PRISMA
    try:
        from core.database import get_db_connection
        from prisma import xgboost_features, xgboost_model, catboost_model, lightgbm_model
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from core.database import get_db_connection
        from prisma import xgboost_features, xgboost_model, catboost_model, lightgbm_model
    
    # Extraction des features pour chaque modèle
    with get_db_connection() as conn:
        features_xgb = xgboost_features.extract_features(data, as_dataframe=False, conn=conn)
        features_cat = xgboost_features.extract_features(data, as_dataframe=True, conn=conn)
        # LightGBM utilise les mêmes features numériques que XGBoost
        features_lgb = features_xgb.copy()

    results = {}
    available_models = []

    # Tentative XGBoost
    try:
        if xgboost_model.is_model_ready():
            results['xgboost'] = xgboost_model.predict_match(features_xgb)
            if results['xgboost']:
                available_models.append('xgboost')
    except Exception as e:
        logger.warning(f"[ENSEMBLE] XGBoost erreur: {e}")

    # Tentative CatBoost
    try:
        if catboost_model.is_model_ready():
            results['catboost'] = catboost_model.predict_match(features_cat)
            if results['catboost']:
                available_models.append('catboost')
    except Exception as e:
        logger.warning(f"[ENSEMBLE] CatBoost erreur: {e}")

    # Tentative LightGBM
    try:
        if lightgbm_model.is_model_ready():
            results['lightgbm'] = lightgbm_model.predict_match(features_lgb)
            if results['lightgbm']:
                available_models.append('lightgbm')
    except Exception as e:
        logger.warning(f"[ENSEMBLE] LightGBM erreur: {e}")

    # Aucun modèle disponible
    if not available_models:
        return None

    # Un seul modèle disponible → utiliser directement
    if len(available_models) == 1:
        model_name = available_models[0]
        result = results[model_name]
        result['source'] = f'{model_name}_solo'
        return result

    # Plusieurs modèles disponibles → Stacking ou Blending
    if use_stacking and len(available_models) >= 2:
        return _predict_with_stacking(results, available_models)
    else:
        return _predict_with_blending(results, available_models)


def _predict_with_stacking(results: Dict, available_models: List[str]) -> dict:
    """
    Utilise le meta-learner pour combiner les prédictions.
    """
    meta_learner = _load_meta_learner()
    
    # Si pas de meta-learner, fallback sur blending
    if meta_learner is None:
        logger.debug("[ENSEMBLE] Pas de meta-learner, fallback sur blending")
        return _predict_with_blending(results, available_models)
    
    try:
        # Construire le vecteur de features pour le meta-learner
        # [prob_1_xgb, prob_x_xgb, prob_2_xgb, prob_1_cat, prob_x_cat, prob_2_cat, ...]
        X_meta = []
        
        for model in ['xgboost', 'catboost', 'lightgbm']:
            if model in results and results[model]:
                probs = results[model]['probabilities']
                X_meta.extend([probs['1'], probs['X'], probs['2']])
            else:
                X_meta.extend([0.33, 0.33, 0.34])  # Valeurs neutres
        
        X_meta = np.array(X_meta).reshape(1, -1)
        
        # Prédiction du meta-learner
        if hasattr(meta_learner, 'predict_proba'):
            meta_probs = meta_learner.predict_proba(X_meta)[0]
        else:
            # Fallback si pas de predict_proba
            return _predict_with_blending(results, available_models)
        
        # Classe gagnante
        class_names = ['1', 'X', '2']
        best_idx = np.argmax(meta_probs)
        best_class = class_names[best_idx]
        confidence = float(meta_probs[best_idx])
        
        # Calibration
        meta_probs = np.clip(meta_probs, 0.05, 0.85)
        meta_probs = meta_probs / meta_probs.sum()
        
        # Agreement entre modèles
        predictions = [results[m]['prediction'] for m in available_models]
        accord = len(set(predictions)) == 1
        
        logger.info(
            f"[ENSEMBLE] Stacking: Models={','.join(available_models)} "
            f"→ {best_class} ({confidence:.2%}) | {'✓ ACCORD' if accord else '⚠ DÉSACCORD'}"
        )
        
        return {
            'prediction': best_class,
            'confidence': confidence,
            'probabilities': {
                '1': float(meta_probs[0]),
                'X': float(meta_probs[1]),
                '2': float(meta_probs[2])
            },
            'source': f'Ensemble_Stacking_{len(available_models)}models',
            'agreement': accord,
            'models': {
                m: {
                    'prediction': results[m]['prediction'],
                    'probabilities': results[m]['probabilities'],
                    'confidence': results[m]['confidence']
                } for m in available_models
            }
        }
        
    except Exception as e:
        logger.warning(f"[ENSEMBLE] Erreur stacking: {e}, fallback sur blending")
        return _predict_with_blending(results, available_models)


def _predict_with_blending(results: Dict, available_models: List[str]) -> dict:
    """
    Combine les modèles avec weighted averaging (blending simple).
    """
    # Récupérer les accuracies pour pondération dynamique
    try:
        from prisma import xgboost_model, catboost_model, lightgbm_model
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from prisma import xgboost_model, catboost_model, lightgbm_model
    
    model_info = {
        'xgboost': xgboost_model.get_model_info(),
        'catboost': catboost_model.get_model_info(),
        'lightgbm': lightgbm_model.get_model_info()
    }
    
    accuracies = {}
    for model in available_models:
        info = model_info.get(model, {})
        if isinstance(info, dict):
            accuracies[model] = info.get('cv_accuracy', 0.5)
        else:
            accuracies[model] = 0.5
    
    # Normaliser les poids
    total_acc = sum(accuracies.values())
    weights = {m: accuracies[m] / total_acc for m in available_models}
    
    # Moyenne pondérée des probabilités
    blend_probs = {'1': 0.0, 'X': 0.0, '2': 0.0}
    for model in available_models:
        probs = results[model]['probabilities']
        weight = weights[model]
        for outcome in ['1', 'X', '2']:
            blend_probs[outcome] += probs[outcome] * weight
    
    # Normaliser
    total_prob = sum(blend_probs.values())
    blend_probs = {k: v / total_prob for k, v in blend_probs.items()}
    
    # Classe gagnante
    best_class = max(blend_probs, key=blend_probs.get)
    blend_confidence = blend_probs[best_class]
    confidence = blend_confidence
    
    # Malus de divergence si les modèles sont en désaccord
    predictions = [results[m]['prediction'] for m in available_models]
    accord = len(set(predictions)) == 1
    
    if not accord and len(available_models) >= 2:
        # Calculer la divergence maximale
        max_divergence = 0
        for i, m1 in enumerate(available_models):
            for m2 in available_models[i+1:]:
                p1 = max(results[m1]['probabilities'].values())
                p2 = max(results[m2]['probabilities'].values())
                divergence = abs(p1 - p2)
                max_divergence = max(max_divergence, divergence)
        
        # Appliquer malus
        if max_divergence > 0.30:
            confidence *= 0.60
        elif max_divergence > 0.20:
            confidence *= 0.80
    
    # Log
    model_str = " ".join([f"{m.upper()}={results[m]['prediction']}({results[m]['confidence']:.1%} w:{weights[m]:.2f})" 
                         for m in available_models])
    logger.info(
        f"[ENSEMBLE] Blend: {model_str} "
        f"→ {best_class}({blend_confidence:.2%} -> Final: {confidence:.2%}) | "
        f"{'✓ ACCORD' if accord else '⚠ DÉSACCORD'}"
    )
    
    return {
        'prediction': best_class,
        'confidence': confidence,
        'blend_confidence': blend_confidence,
        'probabilities': blend_probs,
        'source': f'Ensemble_Blend_{len(available_models)}models',
        'agreement': accord,
        'models': {
            m: {
                'prediction': results[m]['prediction'],
                'probabilities': results[m]['probabilities'],
                'weight': weights[m]
            } for m in available_models
        }
    }


def train_ensemble(conn, force=False, train_meta_learner: bool = True):
    """Entraîne les trois modèles avec triggers intelligents et complexité adaptative."""
    try:
        from prisma import xgboost_model, catboost_model, lightgbm_model
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from prisma import xgboost_model, catboost_model, lightgbm_model
    
    logger.info("[ENSEMBLE] 🚀 DÉMARRAGE ENTRAÎNEMENT ADAPTATIF AVANCÉ (XGB+CAT+LGB)")
    start_time = time.time()
    
    # Récupérer le contexte actuel
    try:
        from core.session_manager import get_active_session
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from core.session_manager import get_active_session
    current_session = get_active_session(conn)
    if not current_session:
        logger.error("[ENSEMBLE] Impossible de déterminer la session actuelle")
        return False
    
    current_session_id = current_session['id']
    current_day = current_session.get('current_day', 1)
    
    logger.info(f"[ENSEMBLE] Contexte: Session {current_session_id}, Journée {current_day}")
    
    # Évaluer les triggers pour tous les modèles
    try:
        from prisma.training_triggers import should_retrain_models, get_training_summary
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from prisma.training_triggers import should_retrain_models, get_training_summary
    
    try:
        decisions = should_retrain_models(conn, current_session_id, current_day)
        # Ajouter décision pour LightGBM si non présente
        if 'lightgbm' not in decisions:
            decisions['lightgbm'] = decisions.get('xgboost', {'should_train': True, 'primary_reason': 'new_model'})
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
        summary = {'models_to_train': [], 'total_triggers': 0}
    
    from prisma.training_status import status_manager
    status_manager.update_global(is_training=True, description="Début du cycle d'entraînement adaptatif...")
    
    # Entraîner les modèles nécessaires
    trained_models = []
    
    # XGBoost
    if decisions['xgboost']['should_train']:
        status_manager.update_model("xgboost", status="training", progress=10)
        logger.info("[ENSEMBLE] 📊 Entraînement XGBoost adaptatif...")
        xgb_success = xgboost_model.train_model(conn, force, decisions['xgboost'])
        if xgb_success:
            trained_models.append('XGBoost')
            status_manager.update_model("xgboost", status="completed", progress=100)
            logger.info("[ENSEMBLE] ✅ XGBoost entraîné avec succès")
        else:
            status_manager.update_model("xgboost", status="failed")
            logger.error("[ENSEMBLE] ❌ Échec entraînement XGBoost")
    else:
        logger.info(f"[ENSEMBLE] ⏸️ XGBoost sauté: {decisions['xgboost']['primary_reason']}")
    
    # CatBoost
    if decisions['catboost']['should_train']:
        status_manager.update_model("catboost", status="training", progress=10)
        logger.info("[ENSEMBLE] 🐈 Entraînement CatBoost adaptatif...")
        cat_success = catboost_model.train_model(conn, force, decisions['catboost'])
        if cat_success:
            trained_models.append('CatBoost')
            status_manager.update_model("catboost", status="completed", progress=100)
            logger.info("[ENSEMBLE] ✅ CatBoost entraîné avec succès")
        else:
            status_manager.update_model("catboost", status="failed")
            logger.error("[ENSEMBLE] ❌ Échec entraînement CatBoost")
    else:
        logger.info(f"[ENSEMBLE] ⏸️ CatBoost sauté: {decisions['catboost']['primary_reason']}")
    
    # LightGBM
    if decisions.get('lightgbm', {}).get('should_train', True):
        status_manager.update_model("lightgbm", status="training", progress=10)
        logger.info("[ENSEMBLE] 🌳 Entraînement LightGBM adaptatif...")
        lgb_success = lightgbm_model.train_model(conn, force, decisions.get('lightgbm'))
        if lgb_success:
            trained_models.append('LightGBM')
            status_manager.update_model("lightgbm", status="completed", progress=100)
            logger.info("[ENSEMBLE] ✅ LightGBM entraîné avec succès")
        else:
            status_manager.update_model("lightgbm", status="failed")
            logger.error("[ENSEMBLE] ❌ Échec entraînement LightGBM")
    else:
        logger.info(f"[ENSEMBLE] ⏸️ LightGBM sauté: {decisions.get('lightgbm', {}).get('primary_reason', 'unknown')}")
    
    # Entraîner le meta-learner si demandé et assez de modèles entraînés
    if train_meta_learner and len(trained_models) >= 2:
        logger.info("[ENSEMBLE] 🧠 Entraînement du meta-learner (stacking)...")
        meta_success = _train_meta_learner(conn, current_session_id)
        if meta_success:
            trained_models.append('MetaLearner')
            logger.info("[ENSEMBLE] ✅ Meta-learner entraîné avec succès")
        else:
            logger.warning("[ENSEMBLE] ⚠️ Échec entraînement meta-learner, fallback sur blending")
    
    # Bilan final
    if trained_models:
        status_manager.update_global(is_training=False, description=f"Entraînement terminé: {', '.join(trained_models)}")
        logger.info(f"[ENSEMBLE] 🎉 ENTRAÎNEMENT TERMINÉ: {', '.join(trained_models)}")
        
        # Afficher les métadonnées finales
        for model_name in trained_models:
            if model_name == 'XGBoost':
                metadata = xgboost_model.get_model_info()
            elif model_name == 'CatBoost':
                metadata = catboost_model.get_model_info()
            elif model_name == 'LightGBM':
                metadata = lightgbm_model.get_model_info()
            else:
                continue
            
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


def _train_meta_learner(conn, session_id: int) -> bool:
    """
    Entraîne le meta-learner pour le stacking.
    Utilise les prédictions out-of-fold des modèles de base.
    """
    try:
        from prisma import xgboost_model, catboost_model, lightgbm_model
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from prisma import xgboost_model, catboost_model, lightgbm_model
    
    try:
        from prisma.session_weighted_training import extract_weighted_training_data
        from prisma import xgboost_features
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from prisma.session_weighted_training import extract_weighted_training_data
        from prisma import xgboost_features
    
    import pandas as pd
    
    try:
        # Extraire données d'entraînement
        X, y = extract_weighted_training_data(conn, session_id, min_matches=200)
        if X is None or len(y) < 200:
            logger.warning("[META-LEARNER] Pas assez de données pour entraîner le meta-learner")
            return False
        
        # Préparer les features numériques (sans strings)
        if hasattr(X, 'iloc'):
            feature_cols = [col for col in X.columns if col not in ['forme_raw_dom', 'forme_raw_ext']]
            X_numeric = X[feature_cols].values.astype('float32')
        else:
            X_numeric = X.astype('float32')
        
        # Générer prédictions out-of-fold avec cross-validation simple
        from sklearn.model_selection import StratifiedKFold
        
        n_splits = 5
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        
        # Charger les modèles
        xgb_model = xgboost_model.load_model()
        cat_model = catboost_model.load_model()
        lgb_model = lightgbm_model.load_model()
        
        if xgb_model is None or cat_model is None:
            logger.warning("[META-LEARNER] Modèles de base non disponibles")
            return False
        
        # Générer meta-features
        meta_features = []
        
        for train_idx, val_idx in skf.split(X_numeric, y):
            X_val = X_numeric[val_idx]
            
            # Prédictions des modèles de base sur le validation set
            fold_meta = []
            
            # XGBoost predictions
            try:
                xgb_probs = xgb_model.predict_proba(X_val)
                fold_meta.extend(xgb_probs[0] if len(xgb_probs.shape) == 1 else xgb_probs[0])
            except:
                fold_meta.extend([0.33, 0.33, 0.34])
            
            # CatBoost predictions (nécessite DataFrame)
            try:
                cat_probs = cat_model.predict_proba(X[val_idx])
                fold_meta.extend(cat_probs[0] if len(cat_probs.shape) == 1 else cat_probs[0])
            except:
                fold_meta.extend([0.33, 0.33, 0.34])
            
            # LightGBM predictions
            if lgb_model:
                try:
                    lgb_probs = lgb_model.predict(X_val)
                    fold_meta.extend(lgb_probs[0] if len(lgb_probs.shape) == 1 else lgb_probs[0])
                except:
                    fold_meta.extend([0.33, 0.33, 0.34])
            else:
                fold_meta.extend([0.33, 0.33, 0.34])
            
            meta_features.append(fold_meta)
        
        # Entraîner meta-learner simple (Logistic Regression)
        X_meta = np.array(meta_features)
        y_meta = y[::n_splits][:len(meta_features)]  # Simplification
        
        if len(X_meta) < 50:
            logger.warning(f"[META-LEARNER] Trop peu d'échantillons: {len(X_meta)}")
            return False
        
        meta_learner = LogisticRegression(
            multi_class='multinomial',
            solver='lbfgs',
            max_iter=1000,
            random_state=42
        )
        meta_learner.fit(X_meta, y_meta)
        
        # Sauvegarder
        _save_meta_learner(meta_learner)
        
        logger.info(f"[META-LEARNER] Entraîné sur {len(X_meta)} échantillons")
        return True
        
    except Exception as e:
        logger.error(f"[META-LEARNER] Erreur entraînement: {e}")
        return False


def get_ensemble_info() -> dict:
    """Retourne le statut des trois modèles pour l'UI/API."""
    try:
        from prisma import xgboost_model, catboost_model, lightgbm_model
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from prisma import xgboost_model, catboost_model, lightgbm_model
    
    # Vérifier meta-learner
    has_meta = _load_meta_learner() is not None

    return {
        'xgboost': xgboost_model.get_model_info(),
        'catboost': catboost_model.get_model_info(),
        'lightgbm': lightgbm_model.get_model_info(),
        'meta_learner_active': has_meta,
        'ensemble_active': (xgboost_model.is_model_ready() and 
                           catboost_model.is_model_ready() and
                           lightgbm_model.is_model_ready()),
        'models_ready': {
            'xgboost': xgboost_model.is_model_ready(),
            'catboost': catboost_model.is_model_ready(),
            'lightgbm': lightgbm_model.is_model_ready()
        }
    }
