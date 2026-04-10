"""
PRISMA Monitoring & Alerting Module
Dashboard de métriques en temps réel et système d'alertes.
"""

import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    """Snapshot des métriques à un instant T."""
    timestamp: str
    session_id: int
    session_day: int
    
    # Métriques de prédiction
    total_predictions: int
    correct_predictions: int
    accuracy: float
    avg_confidence: float
    
    # Métriques financières
    bankroll: float
    profit_session: float
    roi_percentage: float
    
    # Métriques de qualité
    log_loss: float
    brier_score: float
    calibration_error: float
    
    # État des modèles
    models_ready: Dict[str, bool]
    ensemble_active: bool
    last_training: str


class MonitoringDashboard:
    """
    Dashboard de monitoring pour PRISMA.
    Collecte et affiche les métriques clés en temps réel.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.metrics_history = deque(maxlen=1000)  # Historique des 1000 derniers points
        self.alert_thresholds = {
            'min_accuracy': 0.45,
            'max_logloss': 1.0,
            'min_bankroll': 2500,  # Corrigé pour éviter la fausse alerte "critique"
            'max_drawdown': 5000
        }
    
    def collect_snapshot(self, session_id: int) -> MetricSnapshot:
        """Collecte un snapshot des métriques actuelles."""
        cursor = self.conn.cursor()
        
        # Infos session
        cursor.execute("""
            SELECT current_day FROM sessions WHERE id = %s
        """, (session_id,))
        session_info = cursor.fetchone()
        session_day = session_info['current_day'] if session_info else 0
        
        # Métriques de prédiction
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN resultat IS NOT NULL THEN 1 ELSE 0 END) as resolved,
                SUM(CASE WHEN resultat = prediction THEN 1 ELSE 0 END) as correct,
                AVG(fiabilite) as avg_confidence
            FROM predictions
            WHERE session_id = %s
        """, (session_id,))
        pred_stats = cursor.fetchone()
        
        total_pred = pred_stats['total'] or 0
        correct_pred = pred_stats['correct'] or 0
        resolved = pred_stats['resolved'] or 0
        
        accuracy = float(correct_pred) / float(resolved) if resolved > 0 else 0.0
        avg_conf = min(float(pred_stats['avg_confidence'] or 0.5), 1.0) # Plafonnée à 100%
        
        # Métriques financières
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN resultat = 1 THEN profit_net ELSE 0 END), 0) as profit
            FROM historique_paris
            WHERE session_id = %s
        """, (session_id,))
        finance = cursor.fetchone()
        profit = float(finance['profit'] or 0)
        
        # Bankroll
        cursor.execute("""
            SELECT value_int FROM prisma_config WHERE key = 'bankroll_prisma'
        """)
        bankroll_row = cursor.fetchone()
        bankroll = float(bankroll_row['value_int'] if bankroll_row else 20000)
        
        roi = (profit / 20000) * 100 if profit else 0
        
        # État des modèles
        try:
            from prisma.models import xgboost_model, catboost_model, lightgbm_model, ensemble
        except Exception:
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from prisma.models import xgboost_model, catboost_model, lightgbm_model, ensemble
        
        models_ready = {
            'xgboost': xgboost_model.is_model_ready(),
            'catboost': catboost_model.is_model_ready(),
            'lightgbm': lightgbm_model.is_model_ready()
        }
        
        ensemble_info = ensemble.get_ensemble_info()
        
        # Dernier entraînement
        last_training = 'Unknown'
        xgb_meta = xgboost_model.get_model_metadata()
        if xgb_meta and 'trained_at' in xgb_meta:
            last_training = xgb_meta['trained_at']
        
        # Calculer LogLoss et Brier (simplifié)
        logloss, brier = self._calculate_quality_metrics(session_id)
        
        cursor.close()
        
        snapshot = MetricSnapshot(
            timestamp=datetime.now().isoformat(),
            session_id=session_id,
            session_day=session_day,
            total_predictions=total_pred,
            correct_predictions=correct_pred,
            accuracy=accuracy,
            avg_confidence=avg_conf,
            bankroll=bankroll,
            profit_session=profit,
            roi_percentage=roi,
            log_loss=logloss,
            brier_score=brier,
            calibration_error=abs(accuracy - avg_conf),
            models_ready=models_ready,
            ensemble_active=ensemble_info.get('ensemble_active', False),
            last_training=last_training
        )
        
        self.metrics_history.append(snapshot)
        
        return snapshot
    
    def _calculate_quality_metrics(self, session_id: int) -> Tuple[float, float]:
        """Calcule LogLoss et Brier score."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT prediction, resultat, fiabilite, technical_details
            FROM predictions
            WHERE session_id = %s AND resultat IS NOT NULL
        """, (session_id,))
        
        rows = cursor.fetchall()
        cursor.close()
        
        if not rows:
            return 1.0, 0.5
        
        loglosses = []
        briers = []
        
        label_map = {'1': 0, 'X': 1, '2': 2}
        
        for row in rows:
            actual = label_map.get(row['resultat'], 1)
            
            # Extraire probabilités
            tech = row.get('technical_details')
            if isinstance(tech, str):
                try:
                    tech = json.loads(tech)
                except:
                    tech = None
            
            if tech and isinstance(tech, dict):
                probs = tech.get('probabilities', {})
                # Conversion explicite en float
                prob_list = [
                    float(probs.get('1', 0.33)), 
                    float(probs.get('X', 0.33)), 
                    float(probs.get('2', 0.34))
                ]
            else:
                conf = float(row['fiabilite'] or 0.33)
                pred = row['prediction']
                prob_list = [0.05, 0.05, 0.05]
                prob_list[label_map.get(pred, 1)] = conf
                # Normaliser en float
                s = float(sum(prob_list))
                prob_list = [float(p/s) for p in prob_list]
            
            # LogLoss
            eps = 1e-15
            prob_list = [max(eps, min(1-eps, p)) for p in prob_list]
            ll = -np.log(prob_list[actual])
            loglosses.append(ll)
            
            # Brier
            outcomes = [1 if i == actual else 0 for i in range(3)]
            brier = sum((p - o) ** 2 for p, o in zip(prob_list, outcomes)) / 3
            briers.append(brier)
        
        return np.mean(loglosses) if loglosses else 1.0, np.mean(briers) if briers else 0.5
    
    def check_alerts(self, snapshot: MetricSnapshot) -> List[Dict]:
        """Vérifie si des alertes doivent être déclenchées."""
        alerts = []
        
        # Alerte accuracy
        if snapshot.accuracy < self.alert_thresholds['min_accuracy'] and snapshot.total_predictions > 20:
            alerts.append({
                'level': 'WARNING',
                'type': 'low_accuracy',
                'message': f"Accuracy faible: {snapshot.accuracy:.1%} (seuil: {self.alert_thresholds['min_accuracy']:.1%})",
                'timestamp': snapshot.timestamp
            })
        
        # Alerte LogLoss
        if snapshot.log_loss > self.alert_thresholds['max_logloss']:
            alerts.append({
                'level': 'WARNING',
                'type': 'high_logloss',
                'message': f"LogLoss élevé: {snapshot.log_loss:.3f}",
                'timestamp': snapshot.timestamp
            })
        
        # Alerte bankroll
        if snapshot.bankroll < self.alert_thresholds['min_bankroll']:
            alerts.append({
                'level': 'CRITICAL',
                'type': 'low_bankroll',
                'message': f"Bankroll critique: {snapshot.bankroll:,.0f} AR",
                'timestamp': snapshot.timestamp
            })
        
        # Alerte calibration
        if snapshot.calibration_error > 0.15:
            alerts.append({
                'level': 'INFO',
                'type': 'calibration_drift',
                'message': f"Mauvaise calibration: écart={snapshot.calibration_error:.1%}",
                'timestamp': snapshot.timestamp
            })
        
        # Alerte modèles
        if not snapshot.ensemble_active:
            alerts.append({
                'level': 'CRITICAL',
                'type': 'ensemble_inactive',
                'message': "Ensemble non actif - vérifier les modèles",
                'timestamp': snapshot.timestamp
            })
        
        for model, ready in snapshot.models_ready.items():
            if not ready:
                alerts.append({
                    'level': 'WARNING',
                    'type': 'model_unavailable',
                    'message': f"Modèle {model} non disponible",
                    'timestamp': snapshot.timestamp
                })
        
        return alerts
    
    def generate_dashboard(self, session_id: int) -> str:
        """
        Génère un rapport de dashboard complet.
        
        Returns:
            Rapport formaté en texte
        """
        snapshot = self.collect_snapshot(session_id)
        alerts = self.check_alerts(snapshot)
        
        # Calculer tendances
        trends = self._calculate_trends()
        
        dashboard = f"""
╔══════════════════════════════════════════════════════════════════╗
║         📊 PRISMA MONITORING DASHBOARD                           ║
║         {snapshot.timestamp[:19]}                                  ║
╚══════════════════════════════════════════════════════════════════╝

🎯 SESSION #{snapshot.session_id} - JOURNÉE {snapshot.session_day}

📈 PERFORMANCE
  ├─ Prédictions: {snapshot.total_predictions}
  ├─ Accuracy: {snapshot.accuracy:.1%} {trends.get('accuracy_trend', '→')}
  ├─ Confiance moyenne: {snapshot.avg_confidence:.1%}
  ├─ LogLoss: {snapshot.log_loss:.3f} {trends.get('logloss_trend', '→')}
  └─ Brier Score: {snapshot.brier_score:.3f}

💰 FINANCES
  ├─ Bankroll: {snapshot.bankroll:,.0f} AR
  ├─ Profit session: {snapshot.profit_session:+,.0f} AR
  └─ ROI: {snapshot.roi_percentage:+.1f}%

🤖 SYSTÈME
  ├─ Ensemble: {'✅ Actif' if snapshot.ensemble_active else '❌ Inactif'}
  ├─ XGBoost: {'✅' if snapshot.models_ready.get('xgboost') else '❌'}
  ├─ CatBoost: {'✅' if snapshot.models_ready.get('catboost') else '❌'}
  ├─ LightGBM: {'✅' if snapshot.models_ready.get('lightgbm') else '❌'}
  └─ Dernier entraînement: {snapshot.last_training[:10] if snapshot.last_training != 'Unknown' else 'N/A'}

⚠️  ALERTES ({len(alerts)})
"""
        
        if alerts:
            for alert in alerts:
                icon = '🔴' if alert['level'] == 'CRITICAL' else '🟡' if alert['level'] == 'WARNING' else '🔵'
                dashboard += f"  {icon} [{alert['level']}] {alert['message']}\n"
        else:
            dashboard += "  ✅ Aucune alerte - Système nominal\n"
        
        dashboard += """
═══════════════════════════════════════════════════════════════════
"""
        
        # Logger les alertes critiques
        for alert in alerts:
            if alert['level'] == 'CRITICAL':
                logger.error(f"[MONITORING] {alert['message']}")
            elif alert['level'] == 'WARNING':
                logger.warning(f"[MONITORING] {alert['message']}")
        
        return dashboard
    
    def _calculate_trends(self, window: int = 10) -> Dict[str, str]:
        """Calcule les tendances sur la fenêtre récente."""
        if len(self.metrics_history) < window * 2:
            return {}
        
        recent = list(self.metrics_history)[-window:]
        older = list(self.metrics_history)[-(window*2):-window]
        
        trends = {}
        
        # Accuracy trend
        recent_acc = np.mean([m.accuracy for m in recent])
        older_acc = np.mean([m.accuracy for m in older])
        
        if recent_acc > older_acc * 1.05:
            trends['accuracy_trend'] = '📈'
        elif recent_acc < older_acc * 0.95:
            trends['accuracy_trend'] = '📉'
        else:
            trends['accuracy_trend'] = '→'
        
        # LogLoss trend (inverse - plus bas = mieux)
        recent_ll = np.mean([m.log_loss for m in recent])
        older_ll = np.mean([m.log_loss for m in older])
        
        if recent_ll < older_ll * 0.95:
            trends['logloss_trend'] = '📉✅'
        elif recent_ll > older_ll * 1.05:
            trends['logloss_trend'] = '📈❌'
        else:
            trends['logloss_trend'] = '→'
        
        return trends
    
    def export_metrics_json(self, filepath: str = None) -> str:
        """Exporte les métriques en JSON."""
        if filepath is None:
            filepath = f"prisma_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        metrics_list = [asdict(m) for m in self.metrics_history]
        
        with open(filepath, 'w') as f:
            json.dump(metrics_list, f, indent=2, default=str)
        
        logger.info(f"[MONITORING] Métriques exportées: {filepath}")
        return filepath
    
    def get_performance_summary(self, last_n: int = 100) -> Dict:
        """Retourne un résumé des performances récentes."""
        recent = list(self.metrics_history)[-last_n:]
        
        if not recent:
            return {}
        
        return {
            'period_matches': sum(m.total_predictions for m in recent),
            'avg_accuracy': np.mean([m.accuracy for m in recent]),
            'avg_confidence': np.mean([m.avg_confidence for m in recent]),
            'avg_logloss': np.mean([m.log_loss for m in recent]),
            'total_profit': sum(m.profit_session for m in recent),
            'current_bankroll': recent[-1].bankroll if recent else 20000,
            'alerts_triggered': len([a for m in recent for a in self.check_alerts(m)])
        }


class AlertManager:
    """
    Gestionnaire d'alertes avancé.
    Persiste les alertes et gère les notifications.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.alert_history = []
    
    def record_alert(self, alert: Dict):
        """Enregistre une alerte dans l'historique."""
        self.alert_history.append({
            **alert,
            'recorded_at': datetime.now().isoformat()
        })
        
        # Persister en DB si critique
        if alert.get('level') == 'CRITICAL':
            self._persist_alert(alert)
    
    def _persist_alert(self, alert: Dict):
        """Sauvegarde l'alerte en base de données."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO risk_engine_logs 
                (agent, validation_status, rejection_reason, timestamp)
                VALUES (%s, %s, %s, NOW())
            """, ('PRISMA', 'ALERT', alert.get('message', '')))
            self.conn.commit()
            cursor.close()
        except Exception as e:
            logger.warning(f"[ALERT] Erreur persistance alerte: {e}")
    
    def get_alert_summary(self, hours: int = 24) -> Dict:
        """Retourne un résumé des alertes récentes."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        recent = [a for a in self.alert_history 
                 if datetime.fromisoformat(a['timestamp']) > cutoff]
        
        by_level = {}
        by_type = {}
        
        for alert in recent:
            level = alert.get('level', 'INFO')
            by_level[level] = by_level.get(level, 0) + 1
            
            alert_type = alert.get('type', 'unknown')
            by_type[alert_type] = by_type.get(alert_type, 0) + 1
        
        return {
            'total_alerts': len(recent),
            'by_level': by_level,
            'by_type': by_type,
            'most_common': max(by_type, key=by_type.get) if by_type else None
        }


def run_monitoring_check(conn, session_id: int, verbose: bool = True) -> Dict:
    """
    Exécute une vérification complète du monitoring.
    
    Returns:
        Dict avec snapshot et alertes
    """
    dashboard = MonitoringDashboard(conn)
    alert_manager = AlertManager(conn)
    
    # Collecter métriques
    snapshot = dashboard.collect_snapshot(session_id)
    
    # Vérifier alertes
    alerts = dashboard.check_alerts(snapshot)
    
    # Enregistrer alertes
    for alert in alerts:
        alert_manager.record_alert(alert)
    
    # Générer dashboard si verbose
    if verbose:
        report = dashboard.generate_dashboard(session_id)
        print(report)
    
    return {
        'snapshot': snapshot,
        'alerts': alerts,
        'alert_summary': alert_manager.get_alert_summary(),
        'performance_summary': dashboard.get_performance_summary()
    }


def export_dashboard_report(conn, session_id: int, filepath: str = None):
    """Exporte un rapport complet du dashboard."""
    dashboard = MonitoringDashboard(conn)
    
    report = dashboard.generate_dashboard(session_id)
    
    if filepath is None:
        filepath = f"prisma_dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    with open(filepath, 'w') as f:
        f.write(report)
    
    # Exporter aussi en JSON
    json_path = dashboard.export_metrics_json(filepath.replace('.txt', '.json'))
    
    logger.info(f"[MONITORING] Rapport exporté: {filepath}")
    return filepath, json_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, 'f:/Narindra Projet/GODMOD version mobile/Backend/src')
    
    from src.core.db.database import get_db_connection
    from src.core.system.session_manager import get_active_session
    
    with get_db_connection() as conn:
        session = get_active_session(conn)
        if session:
            result = run_monitoring_check(conn, session['id'])
        else:
            print("Aucune session active")
