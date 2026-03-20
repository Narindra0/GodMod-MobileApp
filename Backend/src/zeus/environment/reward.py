from typing import Optional, Tuple


def calculer_recompense(
    mise: int, cote: Optional[float], resultat: Optional[bool], capital_actuel: int, score_zeus: int
) -> Tuple[float, int]:
    """
    Reward ZEUS v2 :
    - reste proportionnelle au profit/perte
    - intègre implicitement le pourcentage de bankroll via la mise
    - garde une forte pénalisation de la banqueroute.
    """
    if resultat is None or mise == 0:
        return 0.0, score_zeus

    # Normalisation principale par 1000 pour rester dans un ordre de grandeur stable.
    scale = 1000.0

    if resultat:
        profit = mise * (cote - 1)
        # Bonus léger pour encourager les paris gagnants même de petite taille.
        reward = (profit / scale) + 0.1
        nouveau_score = score_zeus + 1
        return reward, nouveau_score
    else:
        perte = mise
        # On garde une asymétrie : les pertes sont plus pénalisées que les gains.
        reward = -(perte * 1.5) / scale
        nouveau_score = score_zeus - 1

        # Forte pénalisation si la bankroll approche la banqueroute.
        if capital_actuel < 1000:
            reward -= 10.0

        return reward, nouveau_score


def determiner_resultat(type_pari: str, score_dom: int, score_ext: int) -> bool:
    if type_pari == "Aucun":
        return False
    if score_dom > score_ext:
        issue = "1"
    elif score_dom < score_ext:
        issue = "2"
    else:
        issue = "N"
    return type_pari == issue
