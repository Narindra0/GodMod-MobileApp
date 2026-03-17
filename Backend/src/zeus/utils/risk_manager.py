import logging
from typing import Dict, List, Tuple
logger = logging.getLogger("ZEUS_RISK_MANAGER")
class RiskManager:
    BANKROLL_MIN = 1000
    MISE_MIN = 1000
    SEUIL_ALERTE = 5000
    def __init__(self, capital_initial: int = 20000):
        self.capital_initial = capital_initial
        self.capital_actuel = capital_initial
        self.historique_capital: List[int] = [capital_initial]
        self.alertes: List[str] = []
    def valider_mise(self, montant_demande: int) -> Tuple[bool, int, str]:
        if montant_demande < self.MISE_MIN and montant_demande > 0:
            return False, 0, f"Mise refusée : {montant_demande}Ar est inférieur au minimum de {self.MISE_MIN}Ar."
        max_possible = self.calculer_mise_maximale()
        if montant_demande > max_possible:
            if max_possible < self.MISE_MIN:
                return False, 0, f"Mise bloquée : Bankroll insuffisant ({self.capital_actuel}Ar) pour miser le minimum de {self.MISE_MIN}Ar."
            return False, max_possible, f"Mise plafonnée : {montant_demande}Ar excède la limite de risque. Maximum autorisé : {max_possible}Ar."
        return True, montant_demande, ""
    def calculer_mise_maximale(self) -> int:
        max_mise = self.capital_actuel - self.BANKROLL_MIN
        return max(0, max_mise)
    def mettre_a_jour_capital(self, nouveau_capital: int):
        self.capital_actuel = nouveau_capital
        self.historique_capital.append(nouveau_capital)
        if nouveau_capital <= self.SEUIL_ALERTE and nouveau_capital > self.BANKROLL_MIN:
            msg = f"⚠️ ALERTE : Bankroll critique ! Capital actuel : {nouveau_capital}Ar"
            self.alertes.append(msg)
            logger.warning(msg)
        elif nouveau_capital <= self.BANKROLL_MIN:
            msg = f"🚨 DANGER : Banqueroute imminente ou atteinte ! Capital : {nouveau_capital}Ar"
            self.alertes.append(msg)
            logger.error(msg)
