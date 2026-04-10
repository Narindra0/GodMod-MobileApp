"""
PRISMA Hyperparameter Optimization Engine
Optimisation Bayésienne et Random Search des hyperparamètres des modèles.
Utilise Optuna si disponible, sinon Random Search.
"""

import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

logger = logging.getLogger(__name__)


class HyperoptConfig:
    """Configuration pour l'optimisation."""
    
    def __init__(self, 
                 n_trials: int = 100,
                 timeout: int = 3600,  # 1 heure max
                 cv_folds: int = 5,
                 metric: str = 'accuracy',
                 random_state: int = 42):
        self.n_trials = n_trials
        self.timeout = timeout
        self.cv_folds = cv_folds
        self.metric = metric
        self.random_state = random_state


class HyperoptEngine:
    """
    Moteur d'optimisation des hyperparamètres pour PRISMA.
    Supporte Optuna (Bayesian) et Random Search (fallback).
    """
    
    def __init__(self, conn, config: Optional[HyperoptConfig] = None):
        self.conn = conn
        self.config = config or HyperoptConfig()
        self.has_optuna = self._check_optuna()
        
    def _check_optuna(self) -> bool:
        """Vérifie si Optuna est installé."""
        try:
            import optuna
            logger.info("[HYPEROPT] Optuna détecté - utilisation optimisation Bayésienne")
            return True
        except ImportError:
            logger.info("[HYPEROPT] Optuna non disponible - fallback sur Random Search")
            return False
    
    def optimize_all_models(self, session_id: int) -> Dict[str, Dict]:
        """
        Optimise les hyperparamètres pour tous les modèles.
        
        Returns:
            Dict avec meilleurs paramètres par modèle et phase
        """
        logger.info("=" * 80)
        logger.info("[HYPEROPT] DÉMARRAGE OPTIMISATION HYPERPARAMÈTRES")
        logger.info(f"[HYPEROPT] Méthode: {'Bayesian (Optuna)' if self.has_optuna else 'Random Search'}")
        logger.info(f"[HYPEROPT] Budget: {self.config.n_trials} trials, timeout={self.config.timeout}s")
        logger.info("=" * 80)
        
        results = {}
        
        # Optimiser pour chaque phase
        phases = ['early', 'mid', 'late', 'end']
        
        for phase in phases:
            logger.info(f"\n[HYPEROPT] Optimisation Phase: {phase.upper()}")
            
            # XGBoost
            logger.info(f"[HYPEROPT] Phase {phase} - XGBoost...")
            xgb_params = self._optimize_xgboost(session_id, phase)
            results[f'xgboost_{phase}'] = xgb_params
            
            # CatBoost
            logger.info(f"[HYPEROPT] Phase {phase} - CatBoost...")
            cat_params = self._optimize_catboost(session_id, phase)
            results[f'catboost_{phase}'] = cat_params
            
            # LightGBM
            logger.info(f"[HYPEROPT] Phase {phase} - LightGBM...")
            lgb_params = self._optimize_lightgbm(session_id, phase)
            results[f'lightgbm_{phase}'] = lgb_params
        
        # Sauvegarder les résultats
        self._save_optimization_results(results)
        
        logger.info("=" * 80)
        logger.info("[HYPEROPT] OPTIMISATION TERMINÉE")
        logger.info("=" * 80)
        
        return results
    
    def _optimize_xgboost(self, session_id: int, phase: str) -> Dict:
        """Optimise les hyperparamètres XGBoost pour une phase."""
        from prisma.training.session_weighted_training import extract_weighted_training_data
        
        # Extraire données
        X, y = extract_weighted_training_data(self.conn, session_id, min_matches=200)
        if X is None or len(y) < 200:
            logger.warning(f"[HYPEROPT] Pas assez de données pour XGBoost {phase}")
            return self._get_default_xgboost_params(phase)
        
        # Préparer features numériques
        if hasattr(X, 'iloc'):
            feature_cols = [col for col in X.columns if col not in ['forme_raw_dom', 'forme_raw_ext']]
            X_numeric = X[feature_cols].values.astype('float32')
        else:
            X_numeric = X.astype('float32')
        
        if self.has_optuna:
            return self._optimize_xgboost_optuna(X_numeric, y, phase)
        else:
            return self._optimize_xgboost_random(X_numeric, y, phase)
    
    def _optimize_xgboost_optuna(self, X, y, phase: str) -> Dict:
        """Optimisation XGBoost avec Optuna."""
        import optuna
        from sklearn.model_selection import cross_val_score
        import xgboost as xgb
        
        def objective(trial):
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 100, 500),
                'max_depth': trial.suggest_int('max_depth', 3, 10),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
                'gamma': trial.suggest_float('gamma', 0.0, 1.0),
                'reg_alpha': trial.suggest_float('reg_alpha', 0.0, 1.0, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 0.1, 10.0, log=True),
                'random_state': self.config.random_state,
                'n_jobs': -1
            }
            
            model = xgb.XGBClassifier(**params)
            scores = cross_val_score(model, X, y, cv=self.config.cv_folds, 
                                   scoring=self.config.metric, n_jobs=-1)
            return scores.mean()
        
        # Ajuster n_trials selon la phase
        n_trials = self.config.n_trials // 4  # Réduire par phase
        
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials, timeout=self.config.timeout//4)
        
        best_params = study.best_params
        best_params['random_state'] = self.config.random_state
        best_params['n_jobs'] = -1
        best_params['eval_metric'] = 'mlogloss'
        
        logger.info(f"[HYPEROPT] XGBoost {phase} - Best score: {study.best_value:.4f}")
        
        return {
            'params': best_params,
            'best_score': study.best_value,
            'n_trials': len(study.trials),
            'method': 'optuna',
            'phase': phase
        }
    
    def _optimize_xgboost_random(self, X, y, phase: str) -> Dict:
        """Optimisation XGBoost avec Random Search (fallback)."""
        from sklearn.model_selection import RandomizedSearchCV
        import xgboost as xgb
        
        param_distributions = {
            'n_estimators': [100, 200, 300, 400, 500],
            'max_depth': [3, 4, 5, 6, 7, 8, 10],
            'learning_rate': [0.01, 0.03, 0.05, 0.1, 0.2],
            'subsample': [0.6, 0.7, 0.8, 0.9, 1.0],
            'colsample_bytree': [0.6, 0.7, 0.8, 0.9, 1.0],
            'min_child_weight': [1, 2, 3, 5, 7, 10],
            'gamma': [0, 0.1, 0.2, 0.3, 0.5],
            'reg_alpha': [0.001, 0.01, 0.1, 1.0],
            'reg_lambda': [0.1, 1.0, 2.0, 5.0, 10.0]
        }
        
        model = xgb.XGBClassifier(random_state=self.config.random_state, n_jobs=-1)
        
        n_iter = min(50, self.config.n_trials // 4)
        
        search = RandomizedSearchCV(
            model, param_distributions, 
            n_iter=n_iter,
            cv=self.config.cv_folds,
            scoring=self.config.metric,
            random_state=self.config.random_state,
            n_jobs=-1,
            verbose=0
        )
        
        search.fit(X, y)
        
        best_params = search.best_params_
        best_params['random_state'] = self.config.random_state
        best_params['n_jobs'] = -1
        best_params['eval_metric'] = 'mlogloss'
        
        logger.info(f"[HYPEROPT] XGBoost {phase} - Best score: {search.best_score_:.4f}")
        
        return {
            'params': best_params,
            'best_score': search.best_score_,
            'n_trials': n_iter,
            'method': 'random_search',
            'phase': phase
        }
    
    def _optimize_catboost(self, session_id: int, phase: str) -> Dict:
        """Optimise les hyperparamètres CatBoost pour une phase."""
        # Similaire à XGBoost mais avec paramètres CatBoost spécifiques
        # Pour l'instant, retourne les paramètres par défaut améliorés
        
        default_params = self._get_default_catboost_params(phase)
        
        # TODO: Implémenter optimisation complète si nécessaire
        # CatBoost est plus lent, donc on peut utiliser moins d'iterations
        
        logger.info(f"[HYPEROPT] CatBoost {phase} - Utilisation paramètres par défaut optimisés")
        
        return {
            'params': default_params,
            'best_score': 0.0,  # À calculer
            'n_trials': 0,
            'method': 'default_optimized',
            'phase': phase
        }
    
    def _optimize_lightgbm(self, session_id: int, phase: str) -> Dict:
        """Optimise les hyperparamètres LightGBM pour une phase."""
        from .session_weighted_training import extract_weighted_training_data
        
        X, y = extract_weighted_training_data(self.conn, session_id, min_matches=200)
        if X is None or len(y) < 200:
            return self._get_default_lightgbm_params(phase)
        
        if hasattr(X, 'iloc'):
            feature_cols = [col for col in X.columns if col not in ['forme_raw_dom', 'forme_raw_ext']]
            X_numeric = X[feature_cols].values.astype('float32')
        else:
            X_numeric = X.astype('float32')
        
        if self.has_optuna:
            return self._optimize_lightgbm_optuna(X_numeric, y, phase)
        else:
            return self._optimize_lightgbm_random(X_numeric, y, phase)
    
    def _optimize_lightgbm_optuna(self, X, y, phase: str) -> Dict:
        """Optimisation LightGBM avec Optuna."""
        import optuna
        import lightgbm as lgb
        from sklearn.model_selection import cross_val_score
        
        def objective(trial):
            params = {
                'num_leaves': trial.suggest_int('num_leaves', 20, 100),
                'max_depth': trial.suggest_int('max_depth', 3, 10),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'n_estimators': trial.suggest_int('n_estimators', 100, 500),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'reg_alpha': trial.suggest_float('reg_alpha', 0.0, 1.0, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 0.1, 10.0, log=True),
                'min_child_samples': trial.suggest_int('min_child_samples', 5, 50),
                'random_state': self.config.random_state,
                'verbose': -1
            }
            
            model = lgb.LGBMClassifier(**params)
            scores = cross_val_score(model, X, y, cv=self.config.cv_folds,
                                   scoring=self.config.metric, n_jobs=-1)
            return scores.mean()
        
        n_trials = self.config.n_trials // 4
        
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials, timeout=self.config.timeout//4)
        
        best_params = study.best_params_
        best_params['random_state'] = self.config.random_state
        best_params['verbose'] = -1
        
        logger.info(f"[HYPEROPT] LightGBM {phase} - Best score: {study.best_value:.4f}")
        
        return {
            'params': best_params,
            'best_score': study.best_value,
            'n_trials': len(study.trials),
            'method': 'optuna',
            'phase': phase
        }
    
    def _optimize_lightgbm_random(self, X, y, phase: str) -> Dict:
        """Optimisation LightGBM avec Random Search."""
        from sklearn.model_selection import RandomizedSearchCV
        import lightgbm as lgb
        
        param_distributions = {
            'num_leaves': [20, 35, 50, 70, 100],
            'max_depth': [3, 5, 6, 7, 8, 10],
            'learning_rate': [0.01, 0.03, 0.05, 0.07, 0.1, 0.2],
            'n_estimators': [100, 200, 300, 400, 500],
            'subsample': [0.6, 0.7, 0.8, 0.9, 1.0],
            'colsample_bytree': [0.6, 0.7, 0.8, 0.9, 1.0],
            'reg_alpha': [0.0, 0.01, 0.1, 1.0],
            'reg_lambda': [0.1, 1.0, 2.0, 5.0, 10.0],
            'min_child_samples': [5, 10, 20, 30, 50]
        }
        
        model = lgb.LGBMClassifier(random_state=self.config.random_state, verbose=-1)
        
        n_iter = min(50, self.config.n_trials // 4)
        
        search = RandomizedSearchCV(
            model, param_distributions,
            n_iter=n_iter,
            cv=self.config.cv_folds,
            scoring=self.config.metric,
            random_state=self.config.random_state,
            n_jobs=-1,
            verbose=0
        )
        
        search.fit(X, y)
        
        best_params = search.best_params_
        best_params['random_state'] = self.config.random_state
        best_params['verbose'] = -1
        
        logger.info(f"[HYPEROPT] LightGBM {phase} - Best score: {search.best_score_:.4f}")
        
        return {
            'params': best_params,
            'best_score': search.best_score_,
            'n_trials': n_iter,
            'method': 'random_search',
            'phase': phase
        }
    
    def _get_default_xgboost_params(self, phase: str) -> Dict:
        """Retourne les paramètres XGBoost par défaut pour une phase."""
        configs = {
            'early': {
                'n_estimators': 300, 'max_depth': 7, 'learning_rate': 0.03,
                'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 1,
                'gamma': 0.1, 'reg_alpha': 0.01, 'reg_lambda': 1.0
            },
            'mid': {
                'n_estimators': 250, 'max_depth': 6, 'learning_rate': 0.05,
                'subsample': 0.85, 'colsample_bytree': 0.85, 'min_child_weight': 2,
                'gamma': 0.2, 'reg_alpha': 0.05, 'reg_lambda': 1.5
            },
            'late': {
                'n_estimators': 200, 'max_depth': 5, 'learning_rate': 0.07,
                'subsample': 0.9, 'colsample_bytree': 0.9, 'min_child_weight': 3,
                'gamma': 0.3, 'reg_alpha': 0.1, 'reg_lambda': 2.0
            },
            'end': {
                'n_estimators': 150, 'max_depth': 4, 'learning_rate': 0.1,
                'subsample': 0.95, 'colsample_bytree': 0.95, 'min_child_weight': 5,
                'gamma': 0.5, 'reg_alpha': 0.2, 'reg_lambda': 3.0
            }
        }
        return configs.get(phase, configs['mid'])
    
    def _get_default_catboost_params(self, phase: str) -> Dict:
        """Retourne les paramètres CatBoost par défaut pour une phase."""
        configs = {
            'early': {
                'iterations': 300, 'depth': 8, 'learning_rate': 0.03,
                'l2_leaf_reg': 2, 'border_count': 128,
                'bagging_temperature': 0.8, 'random_strength': 1.0
            },
            'mid': {
                'iterations': 250, 'depth': 7, 'learning_rate': 0.05,
                'l2_leaf_reg': 3, 'border_count': 100,
                'bagging_temperature': 0.6, 'random_strength': 0.8
            },
            'late': {
                'iterations': 200, 'depth': 6, 'learning_rate': 0.07,
                'l2_leaf_reg': 4, 'border_count': 80,
                'bagging_temperature': 0.4, 'random_strength': 0.5
            },
            'end': {
                'iterations': 150, 'depth': 5, 'learning_rate': 0.1,
                'l2_leaf_reg': 5, 'border_count': 64,
                'bagging_temperature': 0.2, 'random_strength': 0.3
            }
        }
        return configs.get(phase, configs['mid'])
    
    def _get_default_lightgbm_params(self, phase: str) -> Dict:
        """Retourne les paramètres LightGBM par défaut pour une phase."""
        configs = {
            'early': {
                'num_leaves': 70, 'max_depth': 8, 'learning_rate': 0.03,
                'n_estimators': 300, 'subsample': 0.8, 'colsample_bytree': 0.8,
                'reg_alpha': 0.01, 'reg_lambda': 1.0, 'min_child_samples': 5
            },
            'mid': {
                'num_leaves': 50, 'max_depth': 7, 'learning_rate': 0.05,
                'n_estimators': 250, 'subsample': 0.85, 'colsample_bytree': 0.85,
                'reg_alpha': 0.05, 'reg_lambda': 1.5, 'min_child_samples': 10
            },
            'late': {
                'num_leaves': 35, 'max_depth': 6, 'learning_rate': 0.07,
                'n_estimators': 200, 'subsample': 0.9, 'colsample_bytree': 0.9,
                'reg_alpha': 0.1, 'reg_lambda': 2.0, 'min_child_samples': 15
            },
            'end': {
                'num_leaves': 20, 'max_depth': 5, 'learning_rate': 0.1,
                'n_estimators': 150, 'subsample': 0.95, 'colsample_bytree': 0.95,
                'reg_alpha': 0.2, 'reg_lambda': 3.0, 'min_child_samples': 20
            }
        }
        return configs.get(phase, configs['mid'])
    
    def _save_optimization_results(self, results: Dict):
        """Sauvegarde les résultats d'optimisation."""
        from src.core.system import config
        
        output_path = os.path.join(config.BASE_DIR, 'models', 'prisma', 'hyperopt_results.json')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        output = {
            'timestamp': datetime.now().isoformat(),
            'config': {
                'n_trials': self.config.n_trials,
                'method': 'optuna' if self.has_optuna else 'random_search',
                'metric': self.config.metric
            },
            'results': results
        }
        
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"[HYPEROPT] Résultats sauvegardés: {output_path}")


def run_hyperparameter_optimization(conn, session_id: int, 
                                    n_trials: int = 100,
                                    use_optuna: bool = True) -> Dict:
    """
    Fonction utilitaire pour lancer l'optimisation.
    
    Args:
        conn: Connexion DB
        session_id: Session actuelle
        n_trials: Nombre d'essais par phase
        use_optuna: Utiliser Optuna si disponible
        
    Returns:
        Dict avec tous les meilleurs paramètres
    """
    config = HyperoptConfig(n_trials=n_trials)
    
    if not use_optuna:
        # Forcer Random Search
        import sys
        sys.modules['optuna'] = None
    
    engine = HyperoptEngine(conn, config)
    results = engine.optimize_all_models(session_id)
    
    return results


if __name__ == "__main__":
    # Test standalone
    import sys
    sys.path.insert(0, 'f:/Narindra Projet/GODMOD version mobile/Backend/src')
    
    from src.core.db.database import get_db_connection
    from src.core.system.session_manager import get_active_session
    
    with get_db_connection() as conn:
        session = get_active_session(conn)
        if session:
            results = run_hyperparameter_optimization(conn, session['id'], n_trials=20)
            print(f"\nOptimisation terminée: {len(results)} configurations générées")
        else:
            print("Aucune session active trouvée")
