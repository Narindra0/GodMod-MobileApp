"""
Pilier 5 — Récompense EV+ (Expected Value Positive).

Philosophie : un pari EV+ qui perd reste une excellente décision.
Un pari EV- qui gagne n'est que de la chance.
ZEUS doit apprendre à raisonner comme un probabiliste, pas comme
quelqu'un qui veut juste "avoir raison" à court terme.
"""
from typing import Optional, Tuple

# Normalisation : 1000 Ar = unité de base
_SCALE = 1000.0

# Seuil EV pour considérer un pari "à valeur"
_EV_VALUE_THRESHOLD = 0.02   # 2% d'edge minimum pour qualifier de "bonne décision"

# Récompenses fixes pour les cas qualitatifs
_BONUS_BONNE_DECISION_GAGNE = 0.20   # EV+ qui gagne
_PARTIAL_CREDIT_EV_PERDU = 0.0       # EV+ qui perd : reward dépend de l'EV attendu
_CHANCE_WIN = 0.05                   # EV- qui gagne (chance, pas skill)
_PUNITION_MAUVAISE_DECISION = 0.30   # Supplément de pénalité pour EV-
_OPPORTUNITE_MANQUEE = -0.10         # Skip sur EV+ disponible > 5%
_BONNE_DISCIPLINE = 0.05             # Skip correct (pas de valeur sur ce match)
_PENALITE_BANQUEROUTE = 10.0         # Pénalité forte si capital < 1000 Ar


def calculer_recompense(
    mise: int,
    cote: Optional[float],
    resultat: Optional[bool],
    capital_actuel: int,
    score_zeus: int,
    ev: float = 0.0,
) -> Tuple[float, int]:
    """
    Récompense ZEUS v2 basée sur l'Expected Value.

    Args:
        mise: Montant misé en Ariary
        cote: Cote jouée (≥ 1.0)
        resultat: True=gagné, False=perdu, None=aucun pari
        capital_actuel: Bankroll après résolution du pari
        score_zeus: Score Zeus courant
        ev: Expected Value du pari (calculé depuis les biais RNG)
             ev > 0 → décision probabilistiquement correcte
             ev ≤ 0 → décision sans valeur

    Returns:
        (reward, nouveau_score_zeus)
    """
    # --- Cas : pas de pari ---
    if resultat is None or mise == 0:
        return 0.0, score_zeus

    pari_ev_positif = ev >= _EV_VALUE_THRESHOLD

    if resultat:
        # === PARI GAGNÉ ===
        profit = mise * (float(cote) - 1.0)
        if pari_ev_positif:
            # Bonne décision + bon résultat : récompense maximale
            reward = (profit / _SCALE) + _BONUS_BONNE_DECISION_GAGNE
        else:
            # Mauvaise décision qui s'est révélée gagnante : chance, pas skill
            reward = _CHANCE_WIN
        nouveau_score = score_zeus + 1

    else:
        # === PARI PERDU ===
        perte = float(mise)
        if pari_ev_positif:
            # Bonne décision EV+ mais mauvaise variance : crédit partiel
            # On récompense proportionnellement à l'EV attendu pour renforcer
            # le comportement correct même en cas de malchance
            reward = max(ev * 0.5, 0.0)
        else:
            # Mauvaise décision ET mauvais résultat : double pénalité
            reward = -(perte * 1.5 / _SCALE) - _PUNITION_MAUVAISE_DECISION
        nouveau_score = score_zeus - 1

    # Pénalité forte si banqueroute imminente
    if capital_actuel < 1000:
        reward -= _PENALITE_BANQUEROUTE

    return reward, nouveau_score


def calculer_recompense_skip(best_ev_disponible: float = 0.0) -> float:
    """
    Récompense pour l'action Skip (action 0 = Aucun pari).

    Args:
        best_ev_disponible: Meilleur EV parmi les 3 paris possibles sur ce match.
                            Si > seuil : on a raté une opportunité.
                            Si ≤ 0 : on a bien fait de ne pas parier.

    Returns:
        reward (float)
    """
    if best_ev_disponible > 0.05:
        # On a ignoré un pari à valeur positive → opportunité manquée
        return _OPPORTUNITE_MANQUEE
    # Aucun pari à valeur sur ce match → bonne discipline
    return _BONNE_DISCIPLINE


def determiner_resultat(type_pari: str, score_dom: int, score_ext: int) -> bool:
    """Détermine si un pari est gagnant selon le score final."""
    if type_pari == "Aucun":
        return False
    if score_dom > score_ext:
        issue = "1"
    elif score_dom < score_ext:
        issue = "2"
    else:
        issue = "N"
    return type_pari == issue
