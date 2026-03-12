"""
Extraction et normalisation des features pour l'observation space.
"""

import sqlite3
from typing import Dict, List, Tuple, Optional
import numpy as np
import logging
from src.core.session_manager import get_active_session

logger = logging.getLogger(__name__)


def calculer_momentum(forme: Optional[str]) -> float:
    """
    Calcule le momentum depuis la chaîne de forme (derniers 5 matchs).
    V = 1.0, N = 0.5, D = 0.0
    
    Args:
        forme: Chaîne comme "VVNDV" ou None
        
    Returns:
        Score de momentum normalisé [0, 1]
    """
    if not forme or len(forme) == 0:
        return 0.5  # Neutre si pas de données
    
    score = 0.0
    for result in forme[-5:]:  # Derniers 5 matchs max
        if result == 'V':
            score += 1.0
        elif result == 'N':
            score += 0.5
        # D = 0.0
    
    # Normaliser par le nombre de matchs (max 5)
    return score / min(len(forme), 5)


def extraire_features_classement(
    equipe_dom_id: int,
    equipe_ext_id: int,
    journee: int,
    conn: sqlite3.Connection
) -> Dict[str, float]:
    """
    Extrait les features de classement pour les deux équipes.
    
    Args:
        equipe_dom_id: ID équipe domicile
        equipe_ext_id: ID équipe extérieur
        journee: Numéro de journée ACTUELLE (on prend journee-1 pour éviter leakage)
        conn: Connexion DB
        
    Returns:
        Dict avec rank_diff, points_diff, momentum_dom, momentum_ext
    """
    cursor = conn.cursor()
    active_session = get_active_session()
    session_id = active_session['id']
    
    # Récupérer classement AVANT ce match pour la session active
    cursor.execute("""
        SELECT equipe_id, position, points, forme
        FROM classement
        WHERE session_id = ? AND journee = (
            SELECT MAX(journee) 
            FROM classement 
            WHERE session_id = ? AND journee < ?
        )
        AND equipe_id IN (?, ?)
    """, (session_id, session_id, journee, equipe_dom_id, equipe_ext_id))
    
    rows = cursor.fetchall()
    
    # Parser les données
    data = {}
    for row in rows:
        equipe_id = row[0]
        data[equipe_id] = {
            'position': row[1] if row[1] is not None else 10,
            'points': row[2] if row[2] is not None else 0,
            'forme': row[3]
        }
    
    # Valeurs par défaut si équipe non trouvée
    dom_data = data.get(equipe_dom_id, {'position': 10, 'points': 0, 'forme': ''})
    ext_data = data.get(equipe_ext_id, {'position': 10, 'points': 0, 'forme': ''})
    
    # Calculer différences
    rank_diff = dom_data['position'] - ext_data['position']  # Négatif = dom mieux classé
    points_diff = dom_data['points'] - ext_data['points']
    
    # Calculer momentum
    momentum_dom = calculer_momentum(dom_data['forme'])
    momentum_ext = calculer_momentum(ext_data['forme'])
    
    return {
        'rank_diff': rank_diff,
        'points_diff': points_diff,
        'momentum_dom': momentum_dom,
        'momentum_ext': momentum_ext
    }


def extraire_features_cotes(cote_1: float, cote_x: float, cote_2: float) -> Dict[str, float]:
    """
    Calcule les probabilités implicites depuis les cotes.
    
    Args:
        cote_1: Cote victoire domicile
        cote_x: Cote match nul
        cote_2: Cote victoire extérieur
        
    Returns:
        Dict avec prob_1, prob_x, prob_2
    """
    # Probabilités implicites (inverses des cotes)
    prob_1 = 1.0 / cote_1 if cote_1 and cote_1 > 0 else 0.33
    prob_x = 1.0 / cote_x if cote_x and cote_x > 0 else 0.33
    prob_2 = 1.0 / cote_2 if cote_2 and cote_2 > 0 else 0.33
    
    # Normaliser pour que la somme = 1 (enlever le margin du bookmaker)
    total = prob_1 + prob_x + prob_2
    if total > 0:
        prob_1 /= total
        prob_x /= total
        prob_2 /= total
    
    return {
        'prob_1': prob_1,
        'prob_x': prob_x,
        'prob_2': prob_2
    }


def construire_observation(
    equipe_dom_id: int,
    equipe_ext_id: int,
    journee: int,
    cote_1: float,
    cote_x: float,
    cote_2: float,
    conn: sqlite3.Connection
) -> np.ndarray:
    """
    Construit le vecteur d'observation complet pour l'agent RL.
    
    Returns:
        Vecteur numpy normalisé [0, 1] de shape (8,)
    """
    # 1. Features de classement
    class_features = extraire_features_classement(
        equipe_dom_id, equipe_ext_id, journee, conn
    )
    
    # 2. Features de cotes
    cote_features = extraire_features_cotes(cote_1, cote_x, cote_2)
    
    # 3. Normalisation et construction du vecteur
    observation = np.array([
        # Différence de classement normalisée (rang entre 1-20, diff entre -19 et 19)
        (class_features['rank_diff'] + 19) / 38,  # [0, 1]
        
        # Différence de points normalisée (estimé max ~60 points)
        (class_features['points_diff'] + 60) / 120,  # [0, 1]
        
        # Momentum déjà normalisé [0, 1]
        class_features['momentum_dom'],
        class_features['momentum_ext'],
        
        # Probabilités implicites déjà normalisées [0, 1]
        cote_features['prob_1'],
        cote_features['prob_x'],
        cote_features['prob_2'],
        
        # Avantage domicile (constant)
        0.55
    ], dtype=np.float32)
    
    # Clip pour sécurité (au cas où)
    observation = np.clip(observation, 0.0, 1.0)
    
    return observation
