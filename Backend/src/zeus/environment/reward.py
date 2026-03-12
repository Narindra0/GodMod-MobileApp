"""
Calcul des récompenses avec pénalité asymétrique.
"""

from typing import Tuple, Optional


def calculer_recompense(
    mise: int,
    cote: Optional[float],
    resultat: Optional[bool],
    capital_actuel: int,
    score_zeus: int
) -> Tuple[float, int]:
    """
    Calcule la récompense RL avec pénalité asymétrique pour les pertes.
    Met également à jour le score ZEUS (+1 victoire, -1 défaite).
    
    Args:
        mise: Montant misé en Ar
        cote: Cote jouée (None si abstention)
        resultat: True si gagné, False si perdu, None si abstention
        capital_actuel: Capital actuel après le pari
        score_zeus: Score actuel de ZEUS
        
    Returns:
        Tuple (reward, nouveau_score_zeus)
    """
    # Cas 1: Abstention
    if resultat is None or mise == 0:
        # Petite pénalité pour encourager l'action (optionnel)
        return -0.1, score_zeus
    
    # Cas 2: Victoire
    if resultat:
        profit = mise * (cote - 1)
        reward = profit
        nouveau_score = score_zeus + 1
        return reward, nouveau_score
    
    # Cas 3: Défaite
    else:
        perte = mise
        # Pénalité asymétrique: les pertes coûtent 1.5x plus cher
        reward = -perte * 1.5
        nouveau_score = score_zeus - 1
        
        # Pénalité terminale si banqueroute
        if capital_actuel < 1000:
            reward -= 10000
        
        return reward, nouveau_score


def determiner_resultat(
    type_pari: str,
    score_dom: int,
    score_ext: int
) -> bool:
    """
    Détermine si un pari est gagné selon le résultat final.
    
    Args:
        type_pari: '1', 'N', '2', ou 'Aucun'
        score_dom: Score équipe domicile
        score_ext: Score équipe extérieur
        
    Returns:
        True si pari gagné, False sinon
    """
    if type_pari == 'Aucun':
        return False
    
    if score_dom > score_ext:
        issue = '1'
    elif score_dom < score_ext:
        issue = '2'
    else:
        issue = 'N'
    
    return type_pari == issue
