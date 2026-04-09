"""
Pilier 4 — Risk Manager avec critère de Kelly.

Les mises fixes arbitraires (1000-2500 Ar) sont remplacées par le
critère de Kelly qui calcule la fraction optimale à miser selon l'edge.
"""
import logging
from typing import List, Tuple

logger = logging.getLogger("ZEUS_RISK_MANAGER")

# Limites de sécurité absolues (Ariary)
_BANKROLL_MIN = 1000       # Capital minimum pour continuer à parier
_MISE_MIN = 1000           # Mise minimale acceptée
_MISE_MAX_ABS = 3000       # Plafond absolu par pari (sécurité)
_SEUIL_ALERTE = 5000       # Seuil d'alerte bankroll faible
_KELLY_FRACTION_CAP = 0.10 # Plafond Kelly : jamais plus de 10% de la bankroll


class RiskManager:
    """
    Gestion du risque pour ZEUS v2.
    Calcule les mises via le critère de Kelly basé sur l'edge estimé.
    """

    def __init__(self, capital_initial: int = 20000):
        self.capital_initial = capital_initial
        self.capital_actuel = capital_initial
        self.historique_capital: List[int] = [capital_initial]
        self.alertes: List[str] = []

    def calculer_mise_kelly(
        self,
        ev: float,
        cote: float,
        capital: int,
    ) -> int:
        """
        Calcule la mise optimale selon le critère de Kelly.

        Kelly : f* = edge / (cote - 1)
        Avec edge = EV du pari = (prob_reelle × cote) - 1

        Args:
            ev:      Expected Value du pari (positif = valeur, négatif = piège)
            cote:    Cote proposée par Bet261 (≥ 1.0)
            capital: Bankroll actuelle en Ar

        Returns:
            Mise en Ariary, entre _MISE_MIN et _MISE_MAX_ABS.
            Retourne 0 si EV ≤ 0 (pas de pari recommandé).
        """
        if ev <= 0.0 or float(cote) <= 1.0:
            return 0

        # Fraction Kelly pure
        kelly_fraction = ev / (float(cote) - 1.0)
        # Plafond de sécurité
        kelly_fraction = min(kelly_fraction, _KELLY_FRACTION_CAP)

        mise = int(kelly_fraction * capital)
        # Arrondir à la centaine inférieure (ex: 1307 -> 1300) pour avoir un montant rond
        mise = (mise // 100) * 100
        
        # Appliquer les limites
        if mise < _MISE_MIN:
            return _MISE_MIN
        return min(mise, _MISE_MAX_ABS)

    def valider_mise(self, montant_demande: int) -> Tuple[bool, int, str]:
        """Valide et plafonne une mise selon la bankroll actuelle."""
        if montant_demande <= 0:
            return True, 0, ""
        if montant_demande < _MISE_MIN:
            return False, 0, (
                f"Mise refusée : {montant_demande}Ar < minimum {_MISE_MIN}Ar."
            )
        max_possible = self.calculer_mise_maximale()
        if montant_demande > max_possible:
            if max_possible < _MISE_MIN:
                return (
                    False,
                    0,
                    f"Bankroll insuffisante ({self.capital_actuel}Ar) pour le minimum {_MISE_MIN}Ar.",
                )
            return (
                False,
                max_possible,
                f"Mise plafonnée : {montant_demande}Ar → {max_possible}Ar (limite risque).",
            )
        return True, montant_demande, ""

    def calculer_mise_maximale(self) -> int:
        """Mise maximale = capital - réserve minimale."""
        return max(0, self.capital_actuel - _BANKROLL_MIN)

    def mettre_a_jour_capital(self, nouveau_capital: int):
        """Met à jour le capital et émet des alertes si nécessaire."""
        self.capital_actuel = nouveau_capital
        self.historique_capital.append(nouveau_capital)
        if _BANKROLL_MIN < nouveau_capital <= _SEUIL_ALERTE:
            msg = f"⚠️ ALERTE : Bankroll critique ! Capital : {nouveau_capital}Ar"
            self.alertes.append(msg)
            logger.warning(msg)
        elif nouveau_capital <= _BANKROLL_MIN:
            msg = f"🚨 DANGER : Banqueroute imminente ! Capital : {nouveau_capital}Ar"
            self.alertes.append(msg)
            logger.error(msg)
