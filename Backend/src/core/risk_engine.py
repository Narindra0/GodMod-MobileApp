import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any, Tuple
from threading import Lock

from . import config
from .database import get_db_connection
from .session_manager import get_active_session

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"


class RejectionReason(Enum):
    GLOBAL_LIMIT_REACHED = "GLOBAL_LIMIT_REACHED"
    AGENT_LIMIT_REACHED = "AGENT_LIMIT_REACHED"
    COOLDOWN_NOT_RESPECTED = "COOLDOWN_NOT_RESPECTED"
    INSUFFICIENT_CAPITAL = "INSUFFICIENT_CAPITAL"
    STOP_LOSS_TRIGGERED = "STOP_LOSS_TRIGGERED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    INSUFFICIENT_CONFIDENCE = "INSUFFICIENT_CONFIDENCE"
    ODDS_TOO_HIGH = "ODDS_TOO_HIGH"
    TOO_MANY_COMBINED_MATCHES = "TOO_MANY_COMBINED_MATCHES"
    SAFE_MODE_ACTIVE = "SAFE_MODE_ACTIVE"
    MINIMUM_SCORE_NOT_MET = "MINIMUM_SCORE_NOT_MET"
    GLOBAL_BLOCK_ACTIVE = "GLOBAL_BLOCK_ACTIVE"


@dataclass
class BetRequest:
    agent: str  # 'ZEUS' ou 'PRISMA'
    session_id: int
    journee: int  # Journée de jeu actuelle
    match_id: int
    bet_type: str  # '1', 'X', '2', 'COMBINED'
    amount: int
    odds: float
    confidence: float
    is_combined: bool = False
    combined_matches_count: int = 1
    zeus_score: Optional[float] = None  # Pour ZEUS uniquement
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BetValidationResult:
    status: ValidationStatus
    reason: Optional[RejectionReason] = None
    message: str = ""
    adjusted_amount: Optional[int] = None  # Montant ajusté (ex: mode SAFE)
    safe_mode_active: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


class RiskEngine:
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._global_block = False
        self._block_reason = None
        self._last_bet_times = {}  # {agent: timestamp}
        logger.info("[RISK-ENGINE] Initialisé - Mode contrôle strict activé")
    
    def validate_bet(self, bet_request: BetRequest) -> BetValidationResult:
        """
        Point d'entrée UNIQUE pour valider un pari.
        Tous les paris DOIVENT passer par cette méthode.
        
        Args:
            bet_request: Les détails du pari à valider
            
        Returns:
            BetValidationResult avec statut ACCEPTED/REJECTED/BLOCKED
        """
        logger.info(f"[RISK-ENGINE] Validation demandée: {bet_request.agent} - {bet_request.bet_type} - {bet_request.amount}Ar")
        
        # 1. Vérifier blocage global
        if self._global_block:
            return self._log_and_return(
                ValidationStatus.BLOCKED,
                RejectionReason.GLOBAL_BLOCK_ACTIVE,
                f"Blocage global actif: {self._block_reason}"
            )
        
        # 2. Vérifier limite globale de paris
        if not self._check_global_limits():
            return self._log_and_return(
                ValidationStatus.REJECTED,
                RejectionReason.GLOBAL_LIMIT_REACHED,
                f"Limite globale atteinte (max {config.MAX_PARIS_SIMULTANÉS_GLOBAL} paris)"
            )
        
        # 3. Vérifier limite par agent
        if not self._check_agent_limits(bet_request.agent):
            agent_limit = config.MAX_PARIS_ZEUS if bet_request.agent == 'ZEUS' else config.MAX_PARIS_PRISMA
            return self._log_and_return(
                ValidationStatus.REJECTED,
                RejectionReason.AGENT_LIMIT_REACHED,
                f"Limite {bet_request.agent} atteinte (max {agent_limit} paris)"
            )
        
        # 4. Vérifier cooldown
        if not self._check_cooldown(bet_request.agent):
            return self._log_and_return(
                ValidationStatus.REJECTED,
                RejectionReason.COOLDOWN_NOT_RESPECTED,
                f"Cooldown non respecté ({config.BET_COOLDOWN_SECONDS}s entre paris)"
            )
        
        # 5. Vérifier capital et stop-loss
        capital_check = self._check_capital_limits(bet_request)
        if not capital_check[0]:
            return self._log_and_return(
                ValidationStatus.REJECTED,
                capital_check[1],
                capital_check[2]
            )
        
        # 6. Vérifier confiance minimum
        if not self._check_confidence(bet_request.confidence, bet_request.agent):
            min_conf = config.PRISMA_MIN_CONFIDENCE if bet_request.agent == 'PRISMA' else config.ZEUS_MIN_SCORE
            return self._log_and_return(
                ValidationStatus.REJECTED,
                RejectionReason.INSUFFICIENT_CONFIDENCE,
                f"Confiance insuffisante ({bet_request.confidence:.2f} < {min_conf})"
            )
        
        # 7. Vérifier limites de cotes (pour combinés)
        if bet_request.is_combined:
            if not self._check_odds_limits(bet_request.odds):
                return self._log_and_return(
                    ValidationStatus.REJECTED,
                    RejectionReason.ODDS_TOO_HIGH,
                    f"Cote combinée trop élevée ({bet_request.odds:.2f} > {config.MAX_COMBINED_ODDS})"
                )
            
            if not self._check_combined_matches_limit(bet_request.combined_matches_count):
                return self._log_and_return(
                    ValidationStatus.REJECTED,
                    RejectionReason.TOO_MANY_COMBINED_MATCHES,
                    f"Trop de matchs combinés ({bet_request.combined_matches_count} > {config.MAX_COMBINED_MATCHES})"
                )
        
        # 8. Vérifier score minimum pour ZEUS
        if bet_request.agent == 'ZEUS' and bet_request.zeus_score is not None:
            if bet_request.zeus_score < config.ZEUS_MIN_SCORE:
                return self._log_and_return(
                    ValidationStatus.REJECTED,
                    RejectionReason.MINIMUM_SCORE_NOT_MET,
                    f"Score ZEUS insuffisant ({bet_request.zeus_score:.2f} < {config.ZEUS_MIN_SCORE})"
                )
        
        # 9. Vérifier mode SAFE pour PRISMA
        if bet_request.agent == 'PRISMA':
            safe_mode_check = self._check_prisma_safe_mode(bet_request.session_id)
            if safe_mode_check[0]:  # Mode SAFE actif
                adjusted_amount = int(bet_request.amount * config.PRISMA_SAFE_MODE_REDUCTION)
                return self._log_and_return(
                    ValidationStatus.ACCEPTED,
                    None,
                    f"Mode SAFE actif - Mise ajustée de {bet_request.amount} à {adjusted_amount}Ar",
                    adjusted_amount=adjusted_amount,
                    safe_mode_active=True
                )
        
        # Toutes validations passées
        self._update_last_bet_time(bet_request.agent)
        return self._log_and_return(
            ValidationStatus.ACCEPTED,
            None,
            "Pari validé - Toutes les conditions respectées",
            adjusted_amount=bet_request.amount
        )
    
    def _check_global_limits(self) -> bool:
        """Vérifie si la limite globale de paris est atteinte"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) as count FROM pari_multiple 
                    WHERE resultat IS NULL AND session_id = (SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1)
                """)
                result = cursor.fetchone()
                active_bets = result['count'] if result else 0
                
                # Vérifier aussi les paris simples non résolus
                cursor.execute("""
                    SELECT COUNT(*) as count FROM historique_paris 
                    WHERE resultat IS NULL AND session_id = (SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1)
                """)
                result = cursor.fetchone()
                active_bets += result['count'] if result else 0
                
                return active_bets < config.MAX_PARIS_SIMULTANÉS_GLOBAL
        except Exception as e:
            logger.error(f"[RISK-ENGINE] Erreur vérification limites globales: {e}")
            return False  # En cas d'erreur, on refuse par précaution
    
    def _check_agent_limits(self, agent: str) -> bool:
        """Vérifie si la limite de paris pour un agent est atteinte"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                limit = config.MAX_PARIS_ZEUS if agent == 'ZEUS' else config.MAX_PARIS_PRISMA
                
                cursor.execute("""
                    SELECT COUNT(*) as count FROM historique_paris 
                    WHERE strategie = %s AND resultat IS NULL AND session_id = (SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1)
                """, (agent,))
                result = cursor.fetchone()
                active_bets = result['count'] if result else 0
                
                # Vérifier aussi les combinés
                cursor.execute("""
                    SELECT COUNT(*) as count FROM pari_multiple 
                    WHERE strategie = %s AND resultat IS NULL AND session_id = (SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1)
                """, (agent,))
                result = cursor.fetchone()
                active_bets += result['count'] if result else 0
                
                return active_bets < limit
        except Exception as e:
            logger.error(f"[RISK-ENGINE] Erreur vérification limites {agent}: {e}")
            return False
    
    def _check_cooldown(self, agent: str) -> bool:
        """Vérifie si le cooldown entre paris est respecté"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT last_bet_timestamp FROM agent_cooldowns 
                    WHERE agent = %s
                """, (agent,))
                result = cursor.fetchone()
                
                if result and result['last_bet_timestamp']:
                    last_bet = result['last_bet_timestamp']
                    if isinstance(last_bet, str):
                        last_bet = datetime.fromisoformat(last_bet)
                    
                    elapsed = (datetime.now() - last_bet).total_seconds()
                    if elapsed < config.BET_COOLDOWN_SECONDS:
                        remaining = config.BET_COOLDOWN_SECONDS - elapsed
                        logger.warning(f"[RISK-ENGINE] Cooldown {agent}: {remaining:.0f}s restantes")
                        return False
                
                return True
        except Exception as e:
            logger.error(f"[RISK-ENGINE] Erreur vérification cooldown {agent}: {e}")
            return False
    
    def _check_capital_limits(self, bet_request: BetRequest) -> Tuple[bool, Optional[RejectionReason], str]:
        """Vérifie les limites de capital (stop-loss, perte quotidienne)"""
        try:
            # Vérifier stop-loss global
            if bet_request.agent == 'ZEUS':
                from .zeus_finance import get_zeus_bankroll
                capital = get_zeus_bankroll()
            else:
                from .prisma_finance import get_prisma_bankroll
                capital = get_prisma_bankroll()
            
            # Vérifier si capital sous seuil critique (Utilise la valeur fixe de config.py)
            min_capital = config.BANKROLL_STOP_LOSS
            if capital < min_capital:
                return (False, RejectionReason.STOP_LOSS_TRIGGERED, 
                        f"Stop-loss atteint: {capital}Ar < {min_capital}Ar")
            
            # Vérifier perte sur le cycle récent (ex: 12 journées)
            # Pour du virtuel, DAILY_LOSS est trop lent, on préfère un cycle glissant
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # Calcul de la perte sur les 12 dernières journées (plus adapté au mode rapide)
                cursor.execute("""
                    SELECT COALESCE(SUM(profit_net), 0) as cycle_loss
                    FROM historique_paris 
                    WHERE strategie = %s 
                    AND session_id = %s
                    AND journee > %s - 12
                    AND profit_net < 0
                """, (bet_request.agent, bet_request.session_id, bet_request.journee))
                result = cursor.fetchone()
                cycle_loss = abs(result['cycle_loss']) if result else 0
                
                if cycle_loss >= config.STOP_DAILY_LOSS:
                    return (False, RejectionReason.DAILY_LOSS_LIMIT,
                            f"Limite perte cycle atteinte: {cycle_loss}Ar (Cycle 12j)")
            
            # Vérifier capital suffisant pour le pari
            if capital < bet_request.amount:
                return (False, RejectionReason.INSUFFICIENT_CAPITAL,
                        f"Capital insuffisant: {capital}Ar < {bet_request.amount}Ar")
            
            return (True, None, "Capital OK")
            
        except Exception as e:
            logger.error(f"[RISK-ENGINE] Erreur vérification capital: {e}")
            return (False, RejectionReason.INSUFFICIENT_CAPITAL, "Erreur vérification capital")
    
    def _check_confidence(self, confidence: float, agent: str) -> bool:
        """Vérifie si le niveau de confiance est suffisant"""
        if agent == 'PRISMA':
            # Vérifier si mode SAFE actif - si oui, seuil plus élevé
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT active FROM prisma_safe_mode 
                        WHERE session_id = (SELECT id FROM sessions WHERE status = 'ACTIVE' LIMIT 1)
                        ORDER BY activated_at DESC LIMIT 1
                    """)
                    result = cursor.fetchone()
                    if result and result['active']:
                        return confidence >= config.PRISMA_SAFE_MODE_CONFIDENCE
            except Exception as e:
                logger.error(f"[RISK-ENGINE] Erreur lecture mode SAFE PRISMA: {e}", exc_info=True)
            return confidence >= config.PRISMA_MIN_CONFIDENCE
        else:  # ZEUS
            return confidence >= config.ZEUS_MIN_SCORE
    
    def _check_odds_limits(self, odds: float) -> bool:
        """Vérifie si la cote est dans les limites acceptables"""
        return odds <= config.MAX_COMBINED_ODDS
    
    def _check_combined_matches_limit(self, count: int) -> bool:
        """Vérifie si le nombre de matchs combinés est acceptable"""
        return count <= config.MAX_COMBINED_MATCHES
    
    def _check_prisma_safe_mode(self, session_id: int) -> Tuple[bool, int]:
        """Vérifie si le mode SAFE est actif pour PRISMA"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier d'abord si mode SAFE déjà actif
                cursor.execute("""
                    SELECT active, consecutive_losses FROM prisma_safe_mode 
                    WHERE session_id = %s AND active = TRUE
                    ORDER BY activated_at DESC LIMIT 1
                """, (session_id,))
                result = cursor.fetchone()
                
                if result and result['active']:
                    return (True, result['consecutive_losses'])
                
                # Sinon, vérifier les pertes consécutives
                cursor.execute("""
                    SELECT resultat FROM historique_paris 
                    WHERE strategie = 'PRISMA' AND session_id = %s
                    ORDER BY id_pari DESC LIMIT %s
                """, (session_id, config.PRISMA_CONSECUTIVE_LOSSES_SAFE))
                results = cursor.fetchall()
                
                if len(results) >= config.PRISMA_CONSECUTIVE_LOSSES_SAFE:
                    losses = sum(1 for r in results if r['resultat'] == 0)
                    if losses >= config.PRISMA_CONSECUTIVE_LOSSES_SAFE:
                        # Activer mode SAFE
                        cursor.execute("""
                            INSERT INTO prisma_safe_mode (session_id, active, consecutive_losses, activated_at)
                            VALUES (%s, TRUE, %s, CURRENT_TIMESTAMP)
                        """, (session_id, losses))
                        logger.warning(f"[RISK-ENGINE] Mode SAFE PRISMA activé ({losses} pertes consécutives)")
                        return (True, losses)
                
                return (False, 0)
                
        except Exception as e:
            logger.error(f"[RISK-ENGINE] Erreur vérification mode SAFE: {e}")
            return (False, 0)
    
    def _update_last_bet_time(self, agent: str):
        """Met à jour le timestamp du dernier pari pour l'agent"""
        try:
            with get_db_connection(write=True) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO agent_cooldowns (agent, last_bet_timestamp, bets_today, last_reset)
                    VALUES (%s, CURRENT_TIMESTAMP, 1, CURRENT_DATE)
                    ON CONFLICT (agent) DO UPDATE SET
                        last_bet_timestamp = EXCLUDED.last_bet_timestamp,
                        bets_today = CASE 
                            WHEN agent_cooldowns.last_reset = CURRENT_DATE 
                            THEN agent_cooldowns.bets_today + 1 
                            ELSE 1 
                        END,
                        last_reset = CURRENT_DATE
                """, (agent,))
        except Exception as e:
            logger.error(f"[RISK-ENGINE] Erreur mise à jour cooldown: {e}")
    
    def _log_and_return(self, status: ValidationStatus, reason: Optional[RejectionReason], 
                       message: str, adjusted_amount: Optional[int] = None,
                       safe_mode_active: bool = False) -> BetValidationResult:
        """Log le résultat et retourne l'objet BetValidationResult"""
        if status == ValidationStatus.ACCEPTED:
            logger.info(f"[RISK-ENGINE] ✓ ACCEPTÉ: {message}")
        else:
            if reason in [RejectionReason.GLOBAL_LIMIT_REACHED, RejectionReason.AGENT_LIMIT_REACHED, RejectionReason.INSUFFICIENT_CONFIDENCE, RejectionReason.COOLDOWN_NOT_RESPECTED]:
                logger.info(f"[RISK-ENGINE] ✗ {status.value}: {reason.value if reason else 'N/A'} - {message}")
            else:
                logger.warning(f"[RISK-ENGINE] ✗ {status.value}: {reason.value if reason else 'N/A'} - {message}")
        
        return BetValidationResult(
            status=status,
            reason=reason,
            message=message,
            adjusted_amount=adjusted_amount,
            safe_mode_active=safe_mode_active
        )
    
    def trigger_global_block(self, reason: str):
        """Active le blocage global de tous les paris"""
        self._global_block = True
        self._block_reason = reason
        logger.critical(f"[RISK-ENGINE] BLOCAGE GLOBAL ACTIVÉ: {reason}")
    
    def release_global_block(self):
        """Désactive le blocage global"""
        self._global_block = False
        self._block_reason = None
        logger.info("[RISK-ENGINE] Blocage global désactivé")
    
    def is_global_blocked(self) -> bool:
        """Vérifie si le blocage global est actif"""
        return self._global_block
    
    def can_resume_betting(self) -> Tuple[bool, str]:
        """Vérifie si les conditions permettent de reprendre les paris"""
        if not self._global_block:
            return (True, "Système opérationnel")
        
        # Vérifier les conditions de rétablissement
        try:
            with get_db_connection() as conn:
                # Vérifier capital
                from .zeus_finance import get_zeus_bankroll
                from .prisma_finance import get_prisma_bankroll
                
                zeus_capital = get_zeus_bankroll(conn)
                prisma_capital = get_prisma_bankroll()
                
                min_capital = config.DEFAULT_BANKROLL * (1 - config.STOP_LOSS_GLOBAL)
                
                if zeus_capital < min_capital or prisma_capital < min_capital:
                    return (False, f"Capital insuffisant (ZEUS: {zeus_capital}Ar, PRISMA: {prisma_capital}Ar)")
                
                return (True, "Conditions rétablies - Capital suffisant")
                
        except Exception as e:
            return (False, f"Erreur vérification: {e}")


# Instance globale du Risk Engine
_risk_engine_instance = None

def get_risk_engine() -> RiskEngine:
    """Retourne l'instance unique du Risk Engine"""
    global _risk_engine_instance
    if _risk_engine_instance is None:
        _risk_engine_instance = RiskEngine()
    return _risk_engine_instance


def validate_bet_request(bet_request: BetRequest) -> BetValidationResult:
    """
    Fonction utilitaire pour valider un pari.
    Point d'entrée simplifié pour les modules externes.
    """
    engine = get_risk_engine()
    return engine.validate_bet(bet_request)
