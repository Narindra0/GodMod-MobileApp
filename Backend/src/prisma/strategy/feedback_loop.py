"""
PRISMA Feedback Loop Module
Boucle de feedback automatique pour l'apprentissage continu.
Analyse les erreurs, ajuste les poids, et détecte le drift de performance.
"""

import logging
import json
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """
    Système de feedback automatique pour PRISMA.
    Analyse les performances post-match et ajuste le système.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.error_history = deque(maxlen=1000)  # Garder 1000 dernières erreurs
        self.performance_window = deque(maxlen=100)  # Fenêtre de performance
        self.drift_threshold = 0.05  # 5% de baisse = alerte
        
    def analyze_recent_predictions(self, session_id: int, 
                                  last_n_matches: int = 50) -> Dict:
        """
        Analyse les prédictions récentes et calcule les métriques d'erreur.
        
        Returns:
            Dict avec analyse des erreurs par type
        """
        cursor = self.conn.cursor()
        
        # Récupérer les prédictions récentes avec résultats
        cursor.execute("""
            SELECT 
                p.id, p.prediction, p.resultat, p.fiabilite,
                p.source, p.technical_details,
                m.cote_1, m.cote_x, m.cote_2,
                m.score_dom, m.score_ext
            FROM predictions p
            JOIN matches m ON p.match_id = m.id
            WHERE p.session_id = %s
            AND p.resultat IS NOT NULL
            AND p.source = 'PRISMA'
            ORDER BY p.id DESC
            LIMIT %s
        """, (session_id, last_n_matches))
        
        predictions = cursor.fetchall()
        cursor.close()
        
        if not predictions:
            logger.warning("[FEEDBACK] Pas de prédictions récentes à analyser")
            return {}
        
        analysis = {
            'total_analyzed': len(predictions),
            'accuracy': 0.0,
            'errors_by_type': defaultdict(int),
            'errors_by_confidence': {'high': 0, 'medium': 0, 'low': 0},
            'errors_by_odds_range': defaultdict(int),
            'confidence_calibration': {'overconfident': 0, 'underconfident': 0, 'calibrated': 0},
            'model_contributions': defaultdict(lambda: {'correct': 0, 'total': 0}),
            'drift_detected': False,
            'recommendations': []
        }
        
        correct = 0
        errors = []
        
        for pred in predictions:
            predicted = pred['prediction']
            actual = pred['resultat']
            confidence = pred['fiabilite'] or 0.5
            
            is_correct = predicted == actual
            
            if is_correct:
                correct += 1
            else:
                errors.append(pred)
                
                # Catégoriser l'erreur
                error_type = self._categorize_error(pred)
                analysis['errors_by_type'][error_type] += 1
                
                # Erreur par niveau de confiance
                conf_level = 'high' if confidence > 0.70 else 'medium' if confidence > 0.55 else 'low'
                analysis['errors_by_confidence'][conf_level] += 1
                
                # Erreur par tranche de cotes
                cotes = [pred['cote_1'], pred['cote_x'], pred['cote_2']]
                min_cote = min(cotes)
                odds_range = self._get_odds_range(min_cote)
                analysis['errors_by_odds_range'][odds_range] += 1
            
            # Calibration de confiance
            if confidence > 0.70 and not is_correct:
                analysis['confidence_calibration']['overconfident'] += 1
            elif confidence < 0.55 and is_correct:
                analysis['confidence_calibration']['underconfident'] += 1
            else:
                analysis['confidence_calibration']['calibrated'] += 1
            
            # Extraire contributions des modèles si disponible
            tech_details = pred.get('technical_details')
            if tech_details and isinstance(tech_details, dict):
                models = tech_details.get('models', {})
                for model_name, model_pred in models.items():
                    analysis['model_contributions'][model_name]['total'] += 1
                    if model_pred.get('prediction') == actual:
                        analysis['model_contributions'][model_name]['correct'] += 1
        
        analysis['accuracy'] = correct / len(predictions) if predictions else 0
        
        # Détecter drift
        self.performance_window.append(analysis['accuracy'])
        if len(self.performance_window) >= 20:
            recent_avg = np.mean(list(self.performance_window)[-10:])
            older_avg = np.mean(list(self.performance_window)[:10])
            
            if older_avg - recent_avg > self.drift_threshold:
                analysis['drift_detected'] = True
                analysis['drift_amount'] = older_avg - recent_avg
                logger.warning(f"[FEEDBACK] ⚠️ DRIFT DÉTECTÉ: -{analysis['drift_amount']:.1%}")
        
        # Générer recommandations
        analysis['recommendations'] = self._generate_recommendations(analysis)
        
        # Logger résumé
        logger.info(f"[FEEDBACK] Analyse {len(predictions)} prédictions: "
                   f"Accuracy={analysis['accuracy']:.1%}, "
                   f"Erreurs={len(errors)}")
        
        if analysis['drift_detected']:
            logger.info(f"[FEEDBACK] 🔴 DRIFT: Performance en baisse de {analysis['drift_amount']:.1%}")
        
        return dict(analysis)
    
    def _categorize_error(self, prediction: Dict) -> str:
        """Catégorise le type d'erreur."""
        predicted = prediction['prediction']
        actual = prediction['resultat']
        cotes = [prediction['cote_1'], prediction['cote_x'], prediction['cote_2']]
        
        # Erreur sur favori clair
        if predicted == '1' and min(cotes) == prediction['cote_1'] and min(cotes) < 1.5:
            return 'favorite_upset'
        
        # Erreur sur outsider
        if actual != predicted:
            actual_cote = {'1': cotes[0], 'X': cotes[1], '2': cotes[2]}.get(actual)
            if actual_cote and actual_cote > 4.0:
                return 'outsider_surprise'
        
        # Erreur sur match équilibré
        if max(cotes) - min(cotes) < 0.5:
            return 'balanced_misread'
        
        # Erreur standard
        return 'standard_error'
    
    def _get_odds_range(self, min_cote: float) -> str:
        """Classifie la tranche de cotes."""
        if min_cote < 1.5:
            return 'favorite'
        elif min_cote < 2.2:
            return 'likely'
        elif min_cote < 3.0:
            return 'balanced'
        elif min_cote < 5.0:
            return 'underdog'
        else:
            return 'longshot'
    
    def _generate_recommendations(self, analysis: Dict) -> List[str]:
        """Génère des recommandations basées sur l'analyse."""
        recommendations = []
        
        # Recommandation drift
        if analysis.get('drift_detected'):
            recommendations.append("URGENT: Réentraîner les modèles - drift de performance détecté")
        
        # Recommandation calibration
        calibration = analysis.get('confidence_calibration', {})
        overconf = calibration.get('overconfident', 0)
        underconf = calibration.get('underconfident', 0)
        total_cal = sum(calibration.values())
        
        if total_cal > 0:
            overconf_pct = overconf / total_cal
            if overconf_pct > 0.3:
                recommendations.append("Étalonner les probabilités (trop d'erreurs en haute confiance)")
        
        # Recommandation par type d'erreur
        errors_by_type = analysis.get('errors_by_type', {})
        if errors_by_type.get('favorite_upset', 0) > errors_by_type.get('outsider_surprise', 0):
            recommendations.append("Améliorer la détection des surprises sur favoris")
        
        if errors_by_type.get('balanced_misread', 0) > 5:
            recommendations.append("Réviser les features pour matchs équilibrés")
        
        # Recommandation par tranche de cotes
        odds_errors = analysis.get('errors_by_odds_range', {})
        if odds_errors.get('longshot', 0) > 3:
            recommendations.append("Exclure les longshots des prédictions")
        
        # Recommandation feature engineering
        if analysis.get('accuracy', 1.0) < 0.45:
            recommendations.append("Envisager de nouvelles features (performance < 45%)")
        
        return recommendations
    
    def adjust_ensemble_weights(self, window_size: int = 50) -> Dict[str, float]:
        """
        Ajuste dynamiquement les poids de l'ensemble basé sur les performances récentes.
        
        Returns:
            Dict avec nouveaux poids par modèle
        """
        cursor = self.conn.cursor()
        
        # Récupérer les prédictions avec détails techniques
        cursor.execute("""
            SELECT technical_details, resultat
            FROM predictions
            WHERE technical_details IS NOT NULL
            AND resultat IS NOT NULL
            ORDER BY id DESC
            LIMIT %s
        """, (window_size,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        if not rows:
            logger.warning("[FEEDBACK] Pas assez de données pour ajuster les poids")
            return {'xgboost': 0.33, 'catboost': 0.33, 'lightgbm': 0.34}
        
        # Calculer accuracy par modèle
        model_scores = defaultdict(lambda: {'correct': 0, 'total': 0})
        
        for row in rows:
            tech_details = row['technical_details']
            actual = row['resultat']
            
            if isinstance(tech_details, str):
                try:
                    tech_details = json.loads(tech_details)
                except:
                    continue
            
            if not isinstance(tech_details, dict):
                continue
            
            models = tech_details.get('models', {})
            for model_name, model_info in models.items():
                model_scores[model_name]['total'] += 1
                if model_info.get('prediction') == actual:
                    model_scores[model_name]['correct'] += 1
        
        # Calculer les poids basés sur l'accuracy
        weights = {}
        total_accuracy = 0
        
        for model_name, scores in model_scores.items():
            if scores['total'] > 0:
                accuracy = scores['correct'] / scores['total']
                weights[model_name] = accuracy
                total_accuracy += accuracy
            else:
                weights[model_name] = 0.33
        
        # Normaliser
        if total_accuracy > 0:
            weights = {k: v / total_accuracy for k, v in weights.items()}
        else:
            weights = {'xgboost': 0.33, 'catboost': 0.33, 'lightgbm': 0.34}
        
        logger.info(f"[FEEDBACK] Poids ajustés: {weights}")
        
        return weights
    
    def detect_market_regime_change(self, session_id: int, 
                                  lookback: int = 100) -> Dict:
        """
        Détecte un changement de régime du marché (cotes devenues moins prédictives).
        
        Returns:
            Dict avec statut du régime et recommandations
        """
        cursor = self.conn.cursor()
        
        # Récupérer corrélation cotes/résultats sur deux périodes
        cursor.execute("""
            SELECT 
                m.cote_1, m.cote_x, m.cote_2,
                m.score_dom, m.score_ext,
                ROW_NUMBER() OVER (ORDER BY m.id) as row_num
            FROM matches m
            WHERE m.session_id = %s
            AND m.score_dom IS NOT NULL
            ORDER BY m.id DESC
            LIMIT %s
        """, (session_id, lookback))
        
        matches = cursor.fetchall()
        cursor.close()
        
        if len(matches) < 40:
            return {'regime_change': False, 'reason': 'insufficient_data'}
        
        # Diviser en deux périodes
        mid = len(matches) // 2
        recent = matches[:mid]
        older = matches[mid:]
        
        # Calculer accuracy des cotes implicites pour chaque période
        def calc_odds_accuracy(match_list):
            correct = 0
            for m in match_list:
                c1 = float(m['cote_1']) if m['cote_1'] is not None else 2.0
                cx = float(m['cote_x']) if m['cote_x'] is not None else 3.0
                c2 = float(m['cote_2']) if m['cote_2'] is not None else 2.0
                probs = [1.0/c1, 1.0/cx, 1.0/c2]
                predicted_idx = np.argmax(probs)
                predicted = ['1', 'X', '2'][predicted_idx]
                
                if m['score_dom'] > m['score_ext']:
                    actual = '1'
                elif m['score_dom'] == m['score_ext']:
                    actual = 'X'
                else:
                    actual = '2'
                
                if predicted == actual:
                    correct += 1
            
            return correct / len(match_list) if match_list else 0
        
        recent_acc = calc_odds_accuracy(recent)
        older_acc = calc_odds_accuracy(older)
        
        regime_change = abs(recent_acc - older_acc) > 0.10  # 10% de différence
        
        result = {
            'regime_change': regime_change,
            'recent_odds_accuracy': recent_acc,
            'older_odds_accuracy': older_acc,
            'difference': recent_acc - older_acc,
            'recommendation': 'recalibrate_features' if regime_change else 'maintain'
        }
        
        if regime_change:
            logger.warning(f"[FEEDBACK] 🚨 CHANGEMENT DE RÉGIME: "
                          f"Cotes accuracy {older_acc:.1%} → {recent_acc:.1%}")
        
        return result
    
    def generate_feedback_report(self, session_id: int) -> str:
        """
        Génère un rapport complet de feedback.
        
        Returns:
            Rapport formaté en texte
        """
        analysis = self.analyze_recent_predictions(session_id)
        weights = self.adjust_ensemble_weights()
        regime = self.detect_market_regime_change(session_id)
        
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║           RAPPORT DE FEEDBACK PRISMA - {datetime.now().strftime('%Y-%m-%d %H:%M')}          ║
╚══════════════════════════════════════════════════════════════════╝

📊 PERFORMANCE RÉCENTE
  • Prédictions analysées: {analysis.get('total_analyzed', 0)}
  • Accuracy: {analysis.get('accuracy', 0):.1%}
  • Drift détecté: {'OUI ⚠️' if analysis.get('drift_detected') else 'Non ✅'}

🎯 RÉPARTITION DES ERREURS
"""
        
        for error_type, count in analysis.get('errors_by_type', {}).items():
            report += f"  • {error_type}: {count}\n"
        
        report += f"""
⚖️ POIDS DE L'ENSEMBLE (AJUSTÉS)
"""
        for model, weight in weights.items():
            report += f"  • {model}: {weight:.1%}\n"
        
        report += f"""
📈 RÉGIME DU MARCHÉ
  • Changement: {'OUI ⚠️' if regime.get('regime_change') else 'Non ✅'}
  • Cotes accuracy (recent): {regime.get('recent_odds_accuracy', 0):.1%}
  • Cotes accuracy (older): {regime.get('older_odds_accuracy', 0):.1%}

💡 RECOMMANDATIONS
"""
        for rec in analysis.get('recommendations', []):
            report += f"  • {rec}\n"
        
        report += """
═══════════════════════════════════════════════════════════════════
"""
        
        return report
    
    def auto_adjust_system(self, session_id: int) -> Dict:
        """
        Ajuste automatiquement le système basé sur le feedback.
        
        Returns:
            Dict avec actions prises
        """
        actions = {
            'timestamp': datetime.now().isoformat(),
            'adjustments_made': [],
            'alerts': []
        }
        
        # 1. Analyser les erreurs
        analysis = self.analyze_recent_predictions(session_id)
        
        # 2. Détecter drift
        if analysis.get('drift_detected'):
            actions['alerts'].append({
                'type': 'performance_drift',
                'severity': 'high',
                'message': f"Drift de {analysis.get('drift_amount', 0):.1%} détecté"
            })
        
        # 3. Ajuster poids
        new_weights = self.adjust_ensemble_weights()
        actions['adjustments_made'].append({
            'type': 'ensemble_weights',
            'new_weights': new_weights
        })
        
        # 4. Détecter changement de régime
        regime = self.detect_market_regime_change(session_id)
        if regime.get('regime_change'):
            actions['alerts'].append({
                'type': 'market_regime_change',
                'severity': 'medium',
                'message': f"Changement de régime: {regime.get('difference', 0):+.1%}"
            })
        
        # 5. Recommander réentraînement si nécessaire
        if analysis.get('accuracy', 1.0) < 0.45 or analysis.get('drift_detected'):
            actions['alerts'].append({
                'type': 'retraining_recommended',
                'severity': 'high',
                'message': "Réentraînement des modèles recommandé"
            })
        
        logger.info("[FEEDBACK] Ajustements automatiques appliqués")
        
        return actions


def run_feedback_analysis(conn, session_id: int) -> Dict:
    """
    Fonction utilitaire pour exécuter l'analyse de feedback complète.
    
    Returns:
        Dict avec toutes les analyses
    """
    feedback = FeedbackLoop(conn)
    
    results = {
        'error_analysis': feedback.analyze_recent_predictions(session_id),
        'adjusted_weights': feedback.adjust_ensemble_weights(),
        'market_regime': feedback.detect_market_regime_change(session_id),
        'auto_adjustments': feedback.auto_adjust_system(session_id),
        'report': feedback.generate_feedback_report(session_id)
    }
    
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, 'f:/Narindra Projet/GODMOD version mobile/Backend/src')
    
    from src.core.db.database import get_db_connection
    from src.core.system.session_manager import get_active_session
    
    with get_db_connection() as conn:
        session = get_active_session(conn)
        if session:
            report = run_feedback_analysis(conn, session['id'])
            print(report['report'])
        else:
            print("Aucune session active")
