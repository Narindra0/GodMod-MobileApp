"""
Module de gestion des risques pour ZEUS.
Gère les limites de mise, les alertes de bankroll et les rapports de risque.
"""

import logging
from typing import Dict, List, Optional, Tuple

# Configuration du logging
logger = logging.getLogger("ZEUS_RISK_MANAGER")

class RiskManager:
    """
    Gère les risques financiers pour l'agent ZEUS.
    """
    
    BANKROLL_MIN = 1000  # Seuil de banqueroute
    MISE_MIN = 1000      # Mise minimale autorisée
    SEUIL_ALERTE = 5000  # Seuil pour déclencher une alerte de bankroll bas
    
    def __init__(self, capital_initial: int = 20000):
        self.capital_initial = capital_initial
        self.capital_actuel = capital_initial
        self.historique_capital: List[int] = [capital_initial]
        self.alertes: List[str] = []
        
    def valider_mise(self, montant_demande: int) -> Tuple[bool, int, str]:
        """
        Valide une mise demandée et retourne le montant autorisé.
        
        Args:
            montant_demande: Le montant que ZEUS souhaite miser.
            
        Returns:
            Tuple (est_valide, montant_autorise, message_erreur)
        """
        # 1. Vérification du montant minimum
        if montant_demande < self.MISE_MIN and montant_demande > 0:
            return False, 0, f"Mise refusée : {montant_demande}Ar est inférieur au minimum de {self.MISE_MIN}Ar."
            
        # 2. Vérification de la capacité financière (ne pas tomber sous BANKROLL_MIN)
        max_possible = self.calculer_mise_maximale()
        
        if montant_demande > max_possible:
            if max_possible < self.MISE_MIN:
                return False, 0, f"Mise bloquée : Bankroll insuffisant ({self.capital_actuel}Ar) pour miser le minimum de {self.MISE_MIN}Ar."
            return False, max_possible, f"Mise plafonnée : {montant_demande}Ar excède la limite de risque. Maximum autorisé : {max_possible}Ar."
            
        return True, montant_demande, ""

    def calculer_mise_maximale(self) -> int:
        """
        Calcule le montant maximum pouvant être misé sans descendre sous le seuil critique.
        """
        # On doit garder au moins BANKROLL_MIN après la mise (au cas où on perdrait tout)
        # Cependant, la mise elle-même est soustraite du bankroll.
        # Donc : Capital - Mise >= BANKROLL_MIN => Mise <= Capital - BANKROLL_MIN
        max_mise = self.capital_actuel - self.BANKROLL_MIN
        return max(0, max_mise)

    def mettre_a_jour_capital(self, nouveau_capital: int):
        """Met à jour le capital et vérifie les alertes."""
        self.capital_actuel = nouveau_capital
        self.historique_capital.append(nouveau_capital)
        
        # Vérification des alertes
        if nouveau_capital <= self.SEUIL_ALERTE and nouveau_capital > self.BANKROLL_MIN:
            msg = f"⚠️ ALERTE : Bankroll critique ! Capital actuel : {nouveau_capital}Ar"
            self.alertes.append(msg)
            logger.warning(msg)
        elif nouveau_capital <= self.BANKROLL_MIN:
            msg = f"🚨 DANGER : Banqueroute imminente ou atteinte ! Capital : {nouveau_capital}Ar"
            self.alertes.append(msg)
            logger.error(msg)

    def generer_rapport_risque(self) -> Dict:
        """Génère un rapport détaillé sur l'évolution et les risques."""
        total_steps = len(self.historique_capital)
        if total_steps < 2:
            return {"status": "Données insuffisantes"}
            
        peak = max(self.historique_capital)
        current = self.capital_actuel
        drawdown = ((peak - current) / peak * 100) if peak > 0 else 0
        
        # Risque de faillite basé sur la tendance récente (simplifié)
        recent_history = self.historique_capital[-10:]
        tendance = recent_history[-1] - recent_history[0] if len(recent_history) > 1 else 0
        
        risk_level = "FAIBLE"
        if current <= self.SEUIL_ALERTE:
            risk_level = "ÉLEVÉ"
        elif drawdown > 30:
            risk_level = "MODÉRÉ"
            
        return {
            "capital_initial": self.capital_initial,
            "capital_actuel": current,
            "profit_perte": current - self.capital_initial,
            "drawdown_max_pct": round(drawdown, 2),
            "niveau_risque": risk_level,
            "nb_alertes": len(self.alertes),
            "derniere_alerte": self.alertes[-1] if self.alertes else None,
            "est_en_faillite": current < self.BANKROLL_MIN
        }
