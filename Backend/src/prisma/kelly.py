"""
PRISMA Kelly Criterion Module
Gestion optimisée des mises pour maximiser la croissance du capital tout en limitant le risque.
"""
import logging
import sys
import os
from typing import Optional

logger = logging.getLogger(__name__)

def calculate_kelly_stake(
    probability: float, 
    odds: float, 
    bankroll: int, 
    fraction: float = 0.2, 
    max_stake: int = 2000,
    min_stake: int = 1000
) -> int:
    """
    Calcule le montant de la mise en Ariary selon le critère de Kelly fractionnaire.
    
    Args:
        probability: Probabilité estimée de gain (0.0 à 1.0)
        odds: Cote offerte par le bookmaker
        bankroll: Capital actuel
        fraction: Multiplicateur de Kelly (Prudence, ex: 0.2 pour 20% de Kelly)
        max_stake: Plafond de mise strict en Ariary
        min_stake: Plancher de mise strict en Ariary
        
    Returns:
        Montant de la mise en Ariary
    """
    if odds <= 1.0:
        return 0
        
    # Cote nette (b)
    b = odds - 1.0
    p = probability
    q = 1.0 - p
    
    # Formule de Kelly : f* = (bp - q) / b
    kelly_f = (b * p - q) / b
    
    # Si l'espérance est négative (Value négative), on ne mise pas
    if kelly_f <= 0:
        logger.info(f"[KELLY] Espérance négative (Prob: {p:.1%}, Cote: {odds:.2f}). Pas de mise.")
        return 0
        
    # Application du Kelly Fractionnaire (Kelly est souvent trop agressif)
    # Un Kelly à 20% (fraction=0.2) est un standard de prudence en betting pro.
    safe_f = kelly_f * fraction
    
    mise_theorique = int(bankroll * safe_f)
    
    # On arrondit à la centaine la plus proche pour la flexibilité (ex: 1500, 1600)
    mise_theorique = (mise_theorique // 100) * 100
    
    # Écrêtage strict entre la mise minimale et maximale
    mise = max(min_stake, min(mise_theorique, max_stake))
        
    logger.info(
        f"[KELLY] Bank: {bankroll} Ar | Prob: {p:.1%} | Cote: {odds:.2f} | "
        f"Kelly Theoretical: {kelly_f:.2%} | Safe Fraction: {safe_f:.2%} | "
        f"Mise: {mise} Ar (Théorique: {mise_theorique})"
    )
    
    return mise

def get_recommended_stake(data: dict, bankroll: int) -> int:
    """
    Helper pour extraire les paramètres d'un objet résultat PRISMA et calculer la mise.
    """
    try:
        from core import config
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from core import config
    
    prob = data.get('confidence', 0.0)
    prediction = data.get('prediction', '')
    
    if not prediction:
        return 0
        
    # On récupère la cote correspondante ('N' ou 'X' -> 'cote_x', '1' -> 'cote_1', '2' -> 'cote_x')
    if prediction.upper() in ['N', 'X']:
        cote_key = "cote_x"
    else:
        cote_key = f"cote_{prediction.lower()}"
    
    odds = data.get(cote_key, 0.0)
    
    if odds <= 0:
        return 0
        
    return calculate_kelly_stake(
        probability=prob,
        odds=odds,
        bankroll=bankroll,
        fraction=getattr(config, 'PRISMA_KELLY_FRACTION', 0.2),
        max_stake=getattr(config, 'PRISMA_MAX_STAKE', 2000),
        min_stake=getattr(config, 'PRISMA_MIN_STAKE', 1000)
    )
