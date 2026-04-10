import sys
import os
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass
from sklearn.metrics import (accuracy_score, log_loss, brier_score_loss, 
                            classification_report, confusion_matrix)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    strategy_name: str
    total_matches: int
    accuracy: float
    log_loss: float
    brier_score: float
    precision_1: float
    precision_x: float
    precision_2: float
    recall_1: float
    recall_x: float
    recall_2: float
    f1_macro: float
    profit_simulation: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None


class ValidationFramework:
    """
    Framework de validation pour PRISMA.
    Implémente back-testing et walk-forward validation.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.results_cache = {}
    
    def run_backtest(self, session_ids: List[int], 
                    strategy: str = 'ensemble',
                    use_filter: bool = True,
                    filter_strategy: str = 'balanced') -> ValidationResult:
        """
        Exécute un back-test sur les sessions spécifiées.
        
        Args:
            session_ids: Liste des sessions à tester
            strategy: 'xgboost', 'catboost', 'lightgbm', ou 'ensemble'
            use_filter: Appliquer le filtrage intelligent
            filter_strategy: 'conservative', 'balanced', 'aggressive'
            
        Returns:
            ValidationResult avec métriques complètes
        """
        logger.info("=" * 80)
        logger.info(f"[VALIDATION] DÉMARRAGE BACK-TEST - Strategy: {strategy}")
        logger.info(f"[VALIDATION] Sessions: {session_ids}")
        logger.info("=" * 80)
        
        # Récupérer toutes les données historiques
        matches_data = self._fetch_historical_matches(session_ids)
        
        if not matches_data:
            logger.error("[VALIDATION] Pas de données pour le back-test")
            return None
        
        logger.info(f"[VALIDATION] {len(matches_data)} matchs chargés")
        
        # Générer prédictions
        predictions = self._generate_predictions(matches_data, strategy)
        
        # Appliquer filtrage si demandé
        if use_filter:
            from .prediction_filter import quick_filter
            predictions = quick_filter(predictions, strategy=filter_strategy)
            logger.info(f"[VALIDATION] Après filtrage: {len(predictions)} prédictions")
        
        # Calculer métriques
        result = self._calculate_metrics(predictions, strategy)
        
        # Simuler profit
        profit_metrics = self._simulate_profit(predictions)
        result.profit_simulation = profit_metrics.get('total_profit')
        result.sharpe_ratio = profit_metrics.get('sharpe_ratio')
        result.max_drawdown = profit_metrics.get('max_drawdown')
        
        logger.info("=" * 80)
        logger.info(f"[VALIDATION] BACK-TEST TERMINÉ")
        logger.info(f"[VALIDATION] Accuracy: {result.accuracy:.2%}")
        logger.info(f"[VALIDATION] LogLoss: {result.log_loss:.4f}")
        logger.info(f"[VALIDATION] Brier Score: {result.brier_score:.4f}")
        logger.info("=" * 80)
        
        return result
    
    def run_walk_forward_validation(self, min_session: int = 1, 
                                   max_session: int = None,
                                   train_window: int = 3,
                                   test_window: int = 1) -> List[ValidationResult]:
        """
        Exécute une validation walk-forward.
        
        Args:
            min_session: Première session à utiliser
            max_session: Dernière session (None = toutes)
            train_window: Nombre de sessions pour entraîner
            test_window: Nombre de sessions pour tester
            
        Returns:
            Liste de ValidationResult par fold
        """
        logger.info("=" * 80)
        logger.info("[VALIDATION] DÉMARRAGE WALK-FORWARD VALIDATION")
        logger.info(f"[VALIDATION] Train window: {train_window}, Test window: {test_window}")
        logger.info("=" * 80)
        
        # Récupérer toutes les sessions disponibles
        all_sessions = self._get_available_sessions()
        
        if max_session:
            all_sessions = [s for s in all_sessions if min_session <= s <= max_session]
        else:
            all_sessions = [s for s in all_sessions if s >= min_session]
        
        if len(all_sessions) < train_window + test_window:
            logger.error("[VALIDATION] Pas assez de sessions pour WFV")
            return []
        
        results = []
        
        # Créer les folds
        for i in range(0, len(all_sessions) - train_window - test_window + 1):
            train_sessions = all_sessions[i:i + train_window]
            test_sessions = all_sessions[i + train_window:i + train_window + test_window]
            
            logger.info(f"\n[VALIDATION] Fold {i+1}: Train={train_sessions}, Test={test_sessions}")
            
            # Entraîner sur train_sessions
            self._train_on_sessions(train_sessions)
            
            # Tester sur test_sessions
            result = self.run_backtest(test_sessions, strategy='ensemble')
            if result:
                result.strategy_name = f"WFV_Fold_{i+1}"
                results.append(result)
        
        logger.info("=" * 80)
        logger.info(f"[VALIDATION] WFV TERMINÉ - {len(results)} folds évalués")
        
        # Calculer moyennes
        if results:
            avg_accuracy = np.mean([r.accuracy for r in results])
            avg_logloss = np.mean([r.log_loss for r in results])
            logger.info(f"[VALIDATION] Moyenne Accuracy: {avg_accuracy:.2%}")
            logger.info(f"[VALIDATION] Moyenne LogLoss: {avg_logloss:.4f}")
        
        logger.info("=" * 80)
        
        return results
    
    def run_ab_test(self, baseline_strategy: str = 'ensemble_old',
                   new_strategy: str = 'ensemble_new',
                   session_ids: List[int] = None) -> Dict:
        """
        Exécute un A/B test entre deux stratégies.
        
        Returns:
            Dict avec comparaison des performances
        """
        if session_ids is None:
            session_ids = self._get_available_sessions()[-5:]  # 5 dernières sessions
        
        logger.info("=" * 80)
        logger.info("[VALIDATION] DÉMARRAGE A/B TEST")
        logger.info(f"[VALIDATION] Baseline: {baseline_strategy}")
        logger.info(f"[VALIDATION] New: {new_strategy}")
        logger.info("=" * 80)
        
        # Test baseline
        baseline_result = self.run_backtest(session_ids, strategy=baseline_strategy)
        
        # Test new strategy
        new_result = self.run_backtest(session_ids, strategy=new_strategy)
        
        # Comparer
        comparison = {
            'baseline': baseline_result,
            'new': new_result,
            'improvements': {}
        }
        
        if baseline_result and new_result:
            comparison['improvements'] = {
                'accuracy_delta': new_result.accuracy - baseline_result.accuracy,
                'logloss_delta': baseline_result.log_loss - new_result.log_loss,  # Négatif = mieux
                'brier_delta': baseline_result.brier_score - new_result.brier_score,
                'profit_delta': (new_result.profit_simulation or 0) - (baseline_result.profit_simulation or 0)
            }
            
            logger.info("\n[VALIDATION] RÉSULTATS A/B TEST:")
            logger.info(f"  Accuracy: {baseline_result.accuracy:.2%} → {new_result.accuracy:.2%} "
                       f"({comparison['improvements']['accuracy_delta']:+.2%})")
            logger.info(f"  LogLoss: {baseline_result.log_loss:.4f} → {new_result.log_loss:.4f} "
                       f"({comparison['improvements']['logloss_delta']:+.4f})")
        
        return comparison
    
    def _fetch_historical_matches(self, session_ids: List[int]) -> List[Dict]:
        """Récupère les données historiques des matchs."""
        cursor = self.conn.cursor()
        
        placeholders = ','.join(['%s'] * len(session_ids))
        query = f"""
            SELECT 
                m.id, m.session_id, m.journee,
                m.equipe_dom_id, m.equipe_ext_id,
                m.cote_1, m.cote_x, m.cote_2,
                m.score_dom, m.score_ext,
                c1.points as pts_dom, c1.forme as forme_dom, 
                c1.buts_pour as bp_dom, c1.buts_contre as bc_dom,
                c2.points as pts_ext, c2.forme as forme_ext,
                c2.buts_pour as bp_ext, c2.buts_contre as bc_ext
            FROM matches m
            LEFT JOIN (
                SELECT DISTINCT ON (equipe_id, session_id)
                    equipe_id, session_id, points, forme, buts_pour, buts_contre
                FROM classement
                ORDER BY equipe_id, session_id, journee DESC
            ) c1 ON c1.equipe_id = m.equipe_dom_id AND c1.session_id = m.session_id
            LEFT JOIN (
                SELECT DISTINCT ON (equipe_id, session_id)
                    equipe_id, session_id, points, forme, buts_pour, buts_contre
                FROM classement
                ORDER BY equipe_id, session_id, journee DESC
            ) c2 ON c2.equipe_id = m.equipe_ext_id AND c2.session_id = m.session_id
            WHERE m.session_id IN ({placeholders})
            AND m.score_dom IS NOT NULL AND m.score_ext IS NOT NULL
            ORDER BY m.session_id, m.journee
        """
        
        cursor.execute(query, tuple(session_ids))
        matches = cursor.fetchall()
        cursor.close()
        
        # Enrichir avec résultat
        enriched = []
        for match in matches:
            match_dict = dict(match)
            
            score_dom = match['score_dom']
            score_ext = match['score_ext']
            
            if score_dom > score_ext:
                match_dict['result'] = '1'
            elif score_dom == score_ext:
                match_dict['result'] = 'X'
            else:
                match_dict['result'] = '2'
            
            enriched.append(match_dict)
        
        return enriched
    
    def _get_available_sessions(self) -> List[int]:
        """Récupère la liste des sessions disponibles."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT id FROM sessions ORDER BY id")
        sessions = [row['id'] for row in cursor.fetchall()]
        cursor.close()
        return sessions
    
    def _generate_predictions(self, matches_data: List[Dict], 
                             strategy: str) -> List[Dict]:
        """Génère les prédictions pour les matchs."""
        # Imports dynamiques pour éviter les problèmes de path
        try:
            from prisma import xgboost_features, xgboost_model, catboost_model
            from prisma.models import lightgbm_model, ensemble
        except ImportError:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from prisma import xgboost_features, xgboost_model, catboost_model
            from prisma.models import lightgbm_model, ensemble
        
        predictions = []
        
        for match in matches_data:
            try:
                # Préparer les données avec validation robuste
                def safe_int(val):
                    try:
                        return int(float(val)) if val is not None else 0
                    except (ValueError, TypeError):
                        return 0
                
                # Vérifier que pts_dom/pts_ext sont bien des nombres (pas des formes comme 'DVDDD')
                pts_dom_raw = match.get('pts_dom')
                pts_ext_raw = match.get('pts_ext')
                
                # Si c'est une string contenant V, N, ou D, c'est probablement une forme - mettre 0
                if isinstance(pts_dom_raw, str) and len(pts_dom_raw) >= 4 and all(c in 'VND' for c in pts_dom_raw):
                    pts_dom = 0
                else:
                    pts_dom = safe_int(pts_dom_raw)
                
                if isinstance(pts_ext_raw, str) and len(pts_ext_raw) >= 4 and all(c in 'VND' for c in pts_ext_raw):
                    pts_ext = 0
                else:
                    pts_ext = safe_int(pts_ext_raw)
                
                data = {
                    'pts_dom': pts_dom,
                    'pts_ext': pts_ext,
                    'forme_dom': match.get('forme_dom') or '',
                    'forme_ext': match.get('forme_ext') or '',
                    'bp_dom': safe_int(match.get('bp_dom')),
                    'bc_dom': safe_int(match.get('bc_dom')),
                    'bp_ext': safe_int(match.get('bp_ext')),
                    'bc_ext': safe_int(match.get('bc_ext')),
                    'cote_1': float(match.get('cote_1') or 2.0),
                    'cote_x': float(match.get('cote_x') or 3.0),
                    'cote_2': float(match.get('cote_2') or 2.0),
                    'equipe_dom_id': match['equipe_dom_id'],
                    'equipe_ext_id': match['equipe_ext_id'],
                    'session_id': match['session_id'],
                    'journee': match['journee']
                }
                
                # Générer prédiction selon stratégie
                if strategy == 'ensemble' or strategy == 'ensemble_new':
                    result = ensemble.predict_ensemble(data, use_stacking=True)
                elif strategy == 'xgboost':
                    features = xgboost_features.extract_features(data, as_dataframe=False, conn=self.conn)
                    result = xgboost_model.predict_match(features)
                elif strategy == 'catboost':
                    features = xgboost_features.extract_features(data, as_dataframe=True, conn=self.conn)
                    result = catboost_model.predict_match(features)
                elif strategy == 'lightgbm':
                    features = xgboost_features.extract_features(data, as_dataframe=False, conn=self.conn)
                    result = lightgbm_model.predict_match(features)
                else:
                    result = None
                
                if result:
                    predictions.append({
                        'match': match,
                        'ensemble_result': result,
                        'match_data': data,
                        'actual_result': match['result']
                    })
                    
            except Exception as e:
                logger.warning(f"[VALIDATION] Erreur prédiction match {match['id']}: {e}")
        
        return predictions
    
    def _calculate_metrics(self, predictions: List[Dict], strategy: str) -> ValidationResult:
        """Calcule les métriques de performance."""
        if not predictions:
            return ValidationResult(strategy_name=strategy, total_matches=0, 
                                  accuracy=0, log_loss=1.0, brier_score=0.5,
                                  precision_1=0, precision_x=0, precision_2=0,
                                  recall_1=0, recall_x=0, recall_2=0, f1_macro=0)
        
        y_true = []
        y_pred = []
        y_proba = []
        
        label_map = {'1': 0, 'X': 1, '2': 2}
        
        for pred in predictions:
            actual = pred['actual_result']
            predicted = pred['ensemble_result']['prediction']
            probs = pred['ensemble_result']['probabilities']
            
            y_true.append(label_map[actual])
            y_pred.append(label_map[predicted])
            y_proba.append([probs['1'], probs['X'], probs['2']])
        
        # Calculer métriques
        accuracy = accuracy_score(y_true, y_pred)
        
        try:
            logloss = log_loss(y_true, y_proba)
        except:
            logloss = 1.0
        
        # Brier score moyen
        brier_scores = []
        for yt, yp in zip(y_true, y_proba):
            brier = sum((yp[i] - (1 if yt == i else 0)) ** 2 for i in range(3)) / 3
            brier_scores.append(brier)
        brier = np.mean(brier_scores)
        
        # Rapport de classification
        report = classification_report(y_true, y_pred, 
                                       target_names=['1', 'X', '2'],
                                       output_dict=True,
                                       zero_division=0)
        
        return ValidationResult(
            strategy_name=strategy,
            total_matches=len(predictions),
            accuracy=accuracy,
            log_loss=logloss,
            brier_score=brier,
            precision_1=report['1']['precision'],
            precision_x=report['X']['precision'],
            precision_2=report['2']['precision'],
            recall_1=report['1']['recall'],
            recall_x=report['X']['recall'],
            recall_2=report['2']['recall'],
            f1_macro=report['macro avg']['f1-score']
        )
    
    def _simulate_profit(self, predictions: List[Dict], 
                        flat_stake: float = 100.0) -> Dict:
        """Simule le profit avec mise fixe."""
        if not predictions:
            return {'total_profit': 0, 'sharpe_ratio': 0, 'max_drawdown': 0}
        
        profits = []
        cumulative = [0]
        max_drawdown = 0
        peak = 0
        
        for pred in predictions:
            predicted = pred['ensemble_result']['prediction']
            actual = pred['actual_result']
            
            # Trouver la cote
            cotes = {
                '1': pred['match_data'].get('cote_1', 2.0),
                'X': pred['match_data'].get('cote_x', 3.0),
                '2': pred['match_data'].get('cote_2', 2.0)
            }
            cote = cotes.get(predicted, 2.0)
            
            # Calculer profit
            if predicted == actual:
                profit = flat_stake * (cote - 1)
            else:
                profit = -flat_stake
            
            profits.append(profit)
            cumulative.append(cumulative[-1] + profit)
            
            # Track drawdown
            if cumulative[-1] > peak:
                peak = cumulative[-1]
            drawdown = peak - cumulative[-1]
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        total_profit = sum(profits)
        
        # Sharpe ratio simplifié
        if len(profits) > 1 and np.std(profits) > 0:
            sharpe = np.mean(profits) / np.std(profits) * np.sqrt(len(profits))
        else:
            sharpe = 0
        
        return {
            'total_profit': total_profit,
            'roi_percentage': (total_profit / (flat_stake * len(predictions))) * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'win_rate': sum(1 for p in profits if p > 0) / len(profits)
        }
    
    def _train_on_sessions(self, session_ids: List[int]):
        """Entraîne les modèles sur les sessions spécifiées."""
        try:
            from prisma.ensemble import train_ensemble
        except ImportError:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from prisma.ensemble import train_ensemble
        
        logger.info(f"[VALIDATION] Entraînement sur sessions {session_ids}")
        
        # Pour WFV, on simule l'entraînement
        # En pratique, il faudrait réentraîner complètement
        # train_ensemble(self.conn, force=True)
        
        logger.info("[VALIDATION] Entraînement simulé (à implémenter)")


def run_comprehensive_validation(conn, baseline_sessions: List[int] = None,
                                 test_sessions: List[int] = None) -> Dict:
    """
    Exécute une validation complète du système.
    
    Returns:
        Dict avec tous les résultats de validation
    """
    framework = ValidationFramework(conn)
    
    if baseline_sessions is None:
        all_sessions = framework._get_available_sessions()
        baseline_sessions = all_sessions[:-2] if len(all_sessions) > 5 else all_sessions[:3]
        test_sessions = all_sessions[-2:] if len(all_sessions) > 2 else all_sessions[-1:]
    
    results = {
        'backtest_baseline': None,
        'backtest_new': None,
        'walk_forward': [],
        'ab_test': None,
        'timestamp': datetime.now().isoformat()
    }
    
    # Back-test baseline (ancien système si disponible)
    logger.info("\n[VALIDATION] 1. BACK-TEST BASELINE")
    results['backtest_baseline'] = framework.run_backtest(
        test_sessions, strategy='xgboost', use_filter=False
    )
    
    # Back-test nouveau système
    logger.info("\n[VALIDATION] 2. BACK-TEST NOUVEAU SYSTÈME")
    results['backtest_new'] = framework.run_backtest(
        test_sessions, strategy='ensemble', use_filter=True, filter_strategy='balanced'
    )
    
    # Walk-forward validation
    logger.info("\n[VALIDATION] 3. WALK-FORWARD VALIDATION")
    results['walk_forward'] = framework.run_walk_forward_validation(
        train_window=3, test_window=1
    )
    
    # A/B test
    logger.info("\n[VALIDATION] 4. A/B TEST")
    results['ab_test'] = framework.run_ab_test(
        baseline_strategy='xgboost',
        new_strategy='ensemble',
        session_ids=test_sessions
    )
    
    return results


def run_validation_suite(conn, sessions_count: int = 2) -> bool:
    """
    Fonction de haut niveau appelée par l'orchestrateur pour valider le système.
    Exécute un back-test sur les sessions récentes.
    """
    try:
        from src.core.system.session_manager import get_active_session
        framework = ValidationFramework(conn)
        
        active_session = get_active_session(conn)
        if not active_session:
            logger.error("[VALIDATION] Aucun session active trouvée pour la suite de validation")
            return False
            
        current_id = active_session['id']
        # On définit les sessions à tester (les N dernières)
        session_ids = [current_id - i for i in range(sessions_count)]
        session_ids = [sid for sid in session_ids if sid > 0]
        
        if not session_ids:
             logger.warning("[VALIDATION] Pas de sessions précédentes pour validation")
             return True # On autorise si c'est la toute première session
             
        result = framework.run_backtest(session_ids, strategy='ensemble')
        
        if result:
            logger.info(f"[VALIDATION] ✅ Suite terminée. Accuracy: {result.accuracy:.2%}")
            return True
        return False
        
    except Exception as e:
        logger.error(f"[VALIDATION] ❌ Erreur dans run_validation_suite: {e}")
        return False


if __name__ == "__main__":
    import sys
    sys.path.insert(0, 'f:/Narindra Projet/GODMOD version mobile/Backend/src')
    
    from src.core.db.database import get_db_connection
    
    with get_db_connection() as conn:
        results = run_comprehensive_validation(conn)
        print("\nValidation terminée!")
