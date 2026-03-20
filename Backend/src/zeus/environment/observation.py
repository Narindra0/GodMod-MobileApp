from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import logging
from src.core.session_manager import get_active_session
logger = logging.getLogger(__name__)
def calculer_momentum(forme: Optional[str]) -> float:
    if not forme or len(forme) == 0:
        return 0.5  
    score = 0.0
    for result in forme[-5:]:  
        if result == 'V':
            score += 1.0
        elif result == 'N':
            score += 0.5
    return score / min(len(forme), 5)
def extraire_features_classement(
    equipe_dom_id: int,
    equipe_ext_id: int,
    journee: int,
    conn: Any,
    session_id: Optional[int] = None
) -> Dict[str, float]:
    cursor = conn.cursor()
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session['id']
    cursor.execute("""
        SELECT equipe_id, position, points, forme
        FROM classement
        WHERE session_id = %s AND journee = (
            SELECT MAX(journee) 
            FROM classement 
            WHERE session_id = %s AND journee < %s
        )
        AND equipe_id IN (%s, %s)
    """, (session_id, session_id, journee, equipe_dom_id, equipe_ext_id))
    rows = cursor.fetchall()
    data = {}
    for row in rows:
        equipe_id = row['equipe_id']
        data[equipe_id] = {
            'position': row['position'] if row['position'] is not None else 10,
            'points': row['points'] if row['points'] is not None else 0,
            'forme': row['forme']
        }
    dom_data = data.get(equipe_dom_id, {'position': 10, 'points': 0, 'forme': ''})
    ext_data = data.get(equipe_ext_id, {'position': 10, 'points': 0, 'forme': ''})
    rank_diff = dom_data['position'] - ext_data['position']  
    points_diff = dom_data['points'] - ext_data['points']
    momentum_dom = calculer_momentum(dom_data['forme'])
    momentum_ext = calculer_momentum(ext_data['forme'])
    return {
        'rank_diff': rank_diff,
        'points_diff': points_diff,
        'momentum_dom': momentum_dom,
        'momentum_ext': momentum_ext
    }
def extraire_features_cotes(cote_1: float, cote_x: float, cote_2: float) -> Dict[str, float]:
    # Convertir Decimal en float si nécessaire
    cote_1 = float(cote_1) if cote_1 is not None else None
    cote_x = float(cote_x) if cote_x is not None else None
    cote_2 = float(cote_2) if cote_2 is not None else None
    
    prob_1 = 1.0 / cote_1 if cote_1 and cote_1 > 0 else 0.33
    prob_x = 1.0 / cote_x if cote_x and cote_x > 0 else 0.33
    prob_2 = 1.0 / cote_2 if cote_2 and cote_2 > 0 else 0.33
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
    conn: Any,
    session_id: Optional[int] = None
) -> np.ndarray:
    class_features = extraire_features_classement(
        equipe_dom_id, equipe_ext_id, journee, conn, session_id
    )
    cote_features = extraire_features_cotes(cote_1, cote_x, cote_2)
    observation = np.array([
        (class_features['rank_diff'] + 19) / 38,  
        (class_features['points_diff'] + 60) / 120,  
        class_features['momentum_dom'],
        class_features['momentum_ext'],
        cote_features['prob_1'],
        cote_features['prob_x'],
        cote_features['prob_2'],
        0.55
    ], dtype=np.float32)
    observation = np.clip(observation, 0.0, 1.0)
    return observation
