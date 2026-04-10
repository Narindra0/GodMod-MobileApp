"""
Module de Monitoring et Dashboard

Fournit des métriques en temps réel sur la santé du système et les performances.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from ..db.database import get_db_connection
from .session_manager import get_active_session
from . import config
from ..finance.risk_engine import get_risk_engine

logger = logging.getLogger(__name__)


@dataclass
class DashboardMetrics:
    """Métriques pour le dashboard"""
    timestamp: datetime
    capital_zeus: int
    capital_prisma: int
    capital_total: int
    roi_daily: float
    roi_weekly: float
    win_rate_zeus: float
    win_rate_prisma: float
    active_bets_zeus: int
    active_bets_prisma: int
    active_bets_total: int
    drawdown_max: float
    validation_acceptance_rate: float
    safe_mode_active: bool
    cooldowns_active: bool
    risk_engine_status: str


@dataclass
class RiskAlert:
    """Alerte de risque"""
    severity: str  # 'CRITICAL', 'WARNING', 'INFO'
    type: str
    message: str
    timestamp: datetime
    data: Dict[str, Any]


class MonitoringSystem:
    """Système de monitoring et d'alertes"""
    
    def __init__(self):
        self.alerts_history: List[RiskAlert] = []
        self.last_check_time: Optional[datetime] = None
        logger.info("[MONITORING] Système de monitoring initialisé")
    
    def get_dashboard_data(self) -> DashboardMetrics:
        """
        Récupère toutes les métriques pour le dashboard
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Capitaux
                from ..finance.zeus_finance import get_zeus_bankroll
                from ..finance.prisma_finance import get_prisma_bankroll
                
                capital_zeus = get_zeus_bankroll(conn)
                capital_prisma = get_prisma_bankroll()
                capital_total = capital_zeus + capital_prisma
                
                # Paris actifs
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN strategie = 'ZEUS' THEN 1 END) as zeus_count,
                        COUNT(CASE WHEN strategie = 'PRISMA' THEN 1 END) as prisma_count
                    FROM (
                        SELECT strategie FROM historique_paris WHERE resultat IS NULL AND created_at > CURRENT_DATE
                        UNION ALL
                        SELECT strategie FROM pari_multiple WHERE resultat IS NULL AND created_at > CURRENT_DATE
                    ) combined
                """)
                result = cursor.fetchone()
                active_bets_zeus = result['zeus_count'] if result else 0
                active_bets_prisma = result['prisma_count'] if result else 0
                active_bets_total = active_bets_zeus + active_bets_prisma
                
                # ROI quotidien
                cursor.execute("""
                    SELECT COALESCE(SUM(profit_net), 0) as daily_profit,
                           COALESCE(SUM(mise_ar), 0) as daily_stake
                    FROM historique_paris
                    WHERE DATE(created_at) = CURRENT_DATE
                """)
                result = cursor.fetchone()
                daily_profit = result['daily_profit'] if result else 0
                daily_stake = result['daily_stake'] if result else 0
                roi_daily = (daily_profit / daily_stake * 100) if daily_stake > 0 else 0.0
                
                # ROI hebdomadaire
                cursor.execute("""
                    SELECT COALESCE(SUM(profit_net), 0) as weekly_profit,
                           COALESCE(SUM(mise_ar), 0) as weekly_stake
                    FROM historique_paris
                    WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                """)
                result = cursor.fetchone()
                weekly_profit = result['weekly_profit'] if result else 0
                weekly_stake = result['weekly_stake'] if result else 0
                roi_weekly = (weekly_profit / weekly_stake * 100) if weekly_stake > 0 else 0.0
                
                # Taux de réussite par agent
                cursor.execute("""
                    SELECT 
                        strategie,
                        COUNT(CASE WHEN resultat = 1 THEN 1 END) as wins,
                        COUNT(CASE WHEN resultat IS NOT NULL THEN 1 END) as total
                    FROM historique_paris
                    WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
                    GROUP BY strategie
                """)
                results = cursor.fetchall()
                win_rates = {}
                for row in results:
                    if row['total'] > 0:
                        win_rates[row['strategie']] = (row['wins'] / row['total']) * 100
                
                win_rate_zeus = win_rates.get('ZEUS', 0.0)
                win_rate_prisma = win_rates.get('PRISMA', 0.0)
                
                # Drawdown maximum
                drawdown_max = self._calculate_max_drawdown(cursor)
                
                # Taux d'acceptation du Risk Engine
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN validation_status = 'ACCEPTED' THEN 1 END) as accepted,
                        COUNT(*) as total
                    FROM risk_engine_logs
                    WHERE timestamp >= CURRENT_DATE - INTERVAL '7 days'
                """)
                result = cursor.fetchone()
                if result and result['total'] > 0:
                    validation_acceptance_rate = (result['accepted'] / result['total']) * 100
                else:
                    validation_acceptance_rate = 100.0
                
                # Mode SAFE actif
                cursor.execute("""
                    SELECT active FROM prisma_safe_mode
                    WHERE active = TRUE AND session_id = (SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1)
                    ORDER BY activated_at DESC LIMIT 1
                """)
                result = cursor.fetchone()
                safe_mode_active = bool(result['active']) if result else False
                
                # Cooldowns actifs
                cursor.execute("""
                    SELECT COUNT(*) as count FROM agent_cooldowns
                    WHERE last_bet_timestamp > CURRENT_TIMESTAMP - INTERVAL '%s seconds'
                """, (config.BET_COOLDOWN_SECONDS,))
                result = cursor.fetchone()
                cooldowns_active = (result['count'] if result else 0) > 0
                
                # Statut Risk Engine
                risk_engine = get_risk_engine()
                risk_engine_status = "BLOQUÉ" if risk_engine.is_global_blocked() else "OPÉRATIONNEL"
                
                return DashboardMetrics(
                    timestamp=datetime.now(),
                    capital_zeus=capital_zeus,
                    capital_prisma=capital_prisma,
                    capital_total=capital_total,
                    roi_daily=roi_daily,
                    roi_weekly=roi_weekly,
                    win_rate_zeus=win_rate_zeus,
                    win_rate_prisma=win_rate_prisma,
                    active_bets_zeus=active_bets_zeus,
                    active_bets_prisma=active_bets_prisma,
                    active_bets_total=active_bets_total,
                    drawdown_max=drawdown_max,
                    validation_acceptance_rate=validation_acceptance_rate,
                    safe_mode_active=safe_mode_active,
                    cooldowns_active=cooldowns_active,
                    risk_engine_status=risk_engine_status
                )
                
        except Exception as e:
            logger.error(f"[MONITORING] Erreur récupération métriques: {e}", exc_info=True)
            return self._get_default_metrics()
    
    def _calculate_max_drawdown(self, cursor) -> float:
        """Calcule le drawdown maximum sur les 30 derniers jours"""
        try:
            cursor.execute("""
                WITH daily_capital AS (
                    SELECT 
                        DATE(timestamp_pari) as date,
                        bankroll_apres as capital
                    FROM historique_paris
                    WHERE timestamp_pari >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY timestamp_pari
                ),
                peaks AS (
                    SELECT 
                        date,
                        capital,
                        MAX(capital) OVER (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) as peak
                    FROM daily_capital
                )
                SELECT 
                    MIN((peak - capital) / NULLIF(peak, 0) * 100) as max_drawdown
                FROM peaks
                WHERE peak > 0
            """)
            result = cursor.fetchone()
            return abs(result['max_drawdown']) if result and result['max_drawdown'] else 0.0
        except Exception as e:
            logger.warning(f"[MONITORING] Erreur calcul drawdown: {e}")
            return 0.0
    
    def _get_default_metrics(self) -> DashboardMetrics:
        """Retourne des métriques par défaut en cas d'erreur"""
        return DashboardMetrics(
            timestamp=datetime.now(),
            capital_zeus=config.DEFAULT_BANKROLL,
            capital_prisma=config.DEFAULT_BANKROLL,
            capital_total=config.DEFAULT_BANKROLL * 2,
            roi_daily=0.0,
            roi_weekly=0.0,
            win_rate_zeus=0.0,
            win_rate_prisma=0.0,
            active_bets_zeus=0,
            active_bets_prisma=0,
            active_bets_total=0,
            drawdown_max=0.0,
            validation_acceptance_rate=100.0,
            safe_mode_active=False,
            cooldowns_active=False,
            risk_engine_status="ERREUR"
        )
    
    def check_anomalies(self) -> List[RiskAlert]:
        """
        Vérifie les anomalies et génère des alertes si nécessaire
        """
        alerts = []
        
        try:
            metrics = self.get_dashboard_data()
            
            # Vérifier stop-loss
            min_capital = config.DEFAULT_BANKROLL * 2 * (1 - config.STOP_LOSS_GLOBAL)
            if metrics.capital_total < min_capital:
                alerts.append(RiskAlert(
                    severity='CRITICAL',
                    type='STOP_LOSS',
                    message=f"Stop-loss atteint: {metrics.capital_total}Ar < {min_capital}Ar",
                    timestamp=datetime.now(),
                    data={'capital': metrics.capital_total, 'threshold': min_capital}
                ))
            
            # Vérifier taux de réussite faible
            if metrics.win_rate_zeus < 40 and metrics.active_bets_zeus >= 10:
                alerts.append(RiskAlert(
                    severity='WARNING',
                    type='LOW_WIN_RATE',
                    message=f"Taux de réussite ZEUS faible: {metrics.win_rate_zeus:.1f}%",
                    timestamp=datetime.now(),
                    data={'agent': 'ZEUS', 'win_rate': metrics.win_rate_zeus}
                ))
            
            if metrics.win_rate_prisma < 50 and metrics.active_bets_prisma >= 5:
                alerts.append(RiskAlert(
                    severity='WARNING',
                    type='LOW_WIN_RATE',
                    message=f"Taux de réussite PRISMA faible: {metrics.win_rate_prisma:.1f}%",
                    timestamp=datetime.now(),
                    data={'agent': 'PRISMA', 'win_rate': metrics.win_rate_prisma}
                ))
            
            # Vérifier drawdown excessif
            if metrics.drawdown_max > 30:
                alerts.append(RiskAlert(
                    severity='CRITICAL',
                    type='HIGH_DRAWDOWN',
                    message=f"Drawdown excessif: {metrics.drawdown_max:.1f}%",
                    timestamp=datetime.now(),
                    data={'drawdown': metrics.drawdown_max}
                ))
            
            # Vérifier ROI négatif sur 7 jours
            if metrics.roi_weekly < -10:
                alerts.append(RiskAlert(
                    severity='WARNING',
                    type='NEGATIVE_ROI',
                    message=f"ROI hebdomadaire négatif: {metrics.roi_weekly:.1f}%",
                    timestamp=datetime.now(),
                    data={'roi_weekly': metrics.roi_weekly}
                ))
            
            # Vérifier blocage Risk Engine
            if metrics.risk_engine_status == "BLOQUÉ":
                alerts.append(RiskAlert(
                    severity='CRITICAL',
                    type='RISK_ENGINE_BLOCKED',
                    message="Risk Engine bloqué - Tous les paris suspendus",
                    timestamp=datetime.now(),
                    data={}
                ))
            
            # Vérifier mode SAFE
            if metrics.safe_mode_active:
                alerts.append(RiskAlert(
                    severity='INFO',
                    type='SAFE_MODE',
                    message="Mode SAFE PRISMA actif - Mises réduites de 50%",
                    timestamp=datetime.now(),
                    data={}
                ))
            
            # Vérifier taux de validation faible
            if metrics.validation_acceptance_rate < 60:
                alerts.append(RiskAlert(
                    severity='WARNING',
                    type='LOW_VALIDATION_RATE',
                    message=f"Taux de validation faible: {metrics.validation_acceptance_rate:.1f}%",
                    timestamp=datetime.now(),
                    data={'acceptance_rate': metrics.validation_acceptance_rate}
                ))
            
            # Enregistrer les alertes
            self.alerts_history.extend(alerts)
            
            # Logger les alertes critiques et warnings
            for alert in alerts:
                if alert.severity == 'CRITICAL':
                    logger.critical(f"[MONITORING-ALERT] {alert.type}: {alert.message}")
                elif alert.severity == 'WARNING':
                    logger.warning(f"[MONITORING-ALERT] {alert.type}: {alert.message}")
                else:
                    logger.info(f"[MONITORING-ALERT] {alert.type}: {alert.message}")
            
            self.last_check_time = datetime.now()
            return alerts
            
        except Exception as e:
            logger.error(f"[MONITORING] Erreur vérification anomalies: {e}", exc_info=True)
            return []
    
    def format_dashboard_console(self, metrics: DashboardMetrics) -> str:
        """
        Formate les métriques pour l'affichage console
        """
        lines = [
            "╔══════════════════════════════════════════════════════════════╗",
            "║                    DASHBOARD GODMOD V2                       ║",
            "╚══════════════════════════════════════════════════════════════╝",
            "",
            f"📊 CAPITAL",
            f"   ZEUS:    {metrics.capital_zeus:,} Ar",
            f"   PRISMA:  {metrics.capital_prisma:,} Ar",
            f"   TOTAL:   {metrics.capital_total:,} Ar",
            "",
            f"📈 PERFORMANCE",
            f"   ROI Jour:   {metrics.roi_daily:+.2f}%",
            f"   ROI 7J:     {metrics.roi_weekly:+.2f}%",
            f"   Win ZEUS:   {metrics.win_rate_zeus:.1f}%",
            f"   Win PRISMA: {metrics.win_rate_prisma:.1f}%",
            f"   Drawdown:   {metrics.drawdown_max:.1f}%",
            "",
            f"🎲 PARIS ACTIFS",
            f"   ZEUS:   {metrics.active_bets_zeus}/{config.MAX_PARIS_ZEUS}",
            f"   PRISMA: {metrics.active_bets_prisma}/{config.MAX_PARIS_PRISMA}",
            f"   Total:  {metrics.active_bets_total}/{config.MAX_PARIS_SIMULTANÉS_GLOBAL}",
            "",
            f"🛡️ SÉCURITÉ",
            f"   Risk Engine: {metrics.risk_engine_status}",
            f"   Safe Mode:   {'✓ ACTIF' if metrics.safe_mode_active else '✗ Inactif'}",
            f"   Validation:  {metrics.validation_acceptance_rate:.1f}%",
            "",
            f"⏰ {metrics.timestamp.strftime('%H:%M:%S')}",
        ]
        return "\n".join(lines)
    
    def get_recent_alerts(self, limit: int = 10) -> List[RiskAlert]:
        """Retourne les alertes récentes"""
        return sorted(
            self.alerts_history,
            key=lambda x: x.timestamp,
            reverse=True
        )[:limit]


# Instance globale du système de monitoring
_monitoring_instance: Optional[MonitoringSystem] = None


def get_monitoring_system() -> MonitoringSystem:
    """Retourne l'instance unique du système de monitoring"""
    global _monitoring_instance
    if _monitoring_instance is None:
        _monitoring_instance = MonitoringSystem()
    return _monitoring_instance


def get_dashboard() -> DashboardMetrics:
    """Fonction utilitaire pour récupérer les métriques du dashboard"""
    return get_monitoring_system().get_dashboard_data()


def check_system_health() -> List[RiskAlert]:
    """Fonction utilitaire pour vérifier la santé du système"""
    return get_monitoring_system().check_anomalies()


def print_dashboard():
    """Affiche le dashboard dans la console"""
    monitoring = get_monitoring_system()
    metrics = monitoring.get_dashboard_data()
    print(monitoring.format_dashboard_console(metrics))
