"""
PRISMA Team Strength Matrix - Module de gestion de la matrice de force relative
Exploite la structure fermée des 20 équipes pour des relations précises entre paires
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# Matrice de force 20x20 : matrix[team_id][opponent_id] = force_score
_matrix: Dict[int, Dict[int, float]] = {}
_last_update: Optional[str] = None

def _get_matrix_path() -> str:
    """Retourne le chemin de sauvegarde de la matrice."""
    from ..core import config
    return os.path.join(config.MODELS_DIR, 'team_strength_matrix.json')

def _initialize_matrix() -> None:
    """Initialise la matrice avec des valeurs neutres (1.0)."""
    global _matrix
    _matrix = {}
    
    # IDs des équipes (1-20 dans votre système)
    for team_id in range(1, 21):
        _matrix[team_id] = {}
        for opponent_id in range(1, 21):
            if team_id != opponent_id:
                _matrix[team_id][opponent_id] = 1.0  # Force neutre initiale
    
    logger.info("[STRENGTH_MATRIX] Matrice 20x20 initialisée avec valeurs neutres")

def load_matrix() -> bool:
    """Charge la matrice depuis le disque."""
    global _matrix, _last_update
    
    matrix_path = _get_matrix_path()
    if not os.path.exists(matrix_path):
        _initialize_matrix()
        save_matrix()
        return True
    
    try:
        with open(matrix_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            _matrix = {int(k): {int(k2): v for k2, v in v.items()} for k, v in data['matrix'].items()}
            _last_update = data.get('last_update')
        
        logger.info(f"[STRENGTH_MATRIX] Matrice chargée. Dernière mise à jour: {_last_update}")
        return True
    except Exception as e:
        logger.error(f"[STRENGTH_MATRIX] Erreur chargement matrice: {e}")
        _initialize_matrix()
        return False

def save_matrix() -> None:
    """Sauvegarde la matrice sur le disque."""
    global _last_update
    
    matrix_path = _get_matrix_path()
    os.makedirs(os.path.dirname(matrix_path), exist_ok=True)
    
    _last_update = datetime.now().isoformat()
    
    data = {
        'matrix': _matrix,
        'last_update': _last_update,
        'version': '1.0'
    }
    
    try:
        with open(matrix_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"[STRENGTH_MATRIX] Matrice sauvegardée: {len(_matrix)} équipes")
    except Exception as e:
        logger.error(f"[STRENGTH_MATRIX] Erreur sauvegarde matrice: {e}")

def get_relative_strength(team_id: int, opponent_id: int) -> float:
    """Retourne la force relative d'une équipe contre une autre."""
    if team_id == opponent_id:
        return 1.0
    
    if team_id not in _matrix or opponent_id not in _matrix[team_id]:
        logger.debug(f"[STRENGTH_MATRIX] Paire inconnue: {team_id} vs {opponent_id}")
        return 1.0
    
    return _matrix[team_id][opponent_id]

def update_strength_matrix(conn, session_id: int, journee: int) -> None:
    """
    Met à jour la matrice de force avec les résultats de la journée.
    
    Args:
        conn: Connexion DB active
        session_id: ID de la session
        journee: Numéro de la journée
    """
    global _matrix
    
    try:
        cursor = conn.cursor()
        
        # Récupérer tous les matchs de la journée avec résultats
        cursor.execute("""
            SELECT equipe_dom_id, equipe_ext_id, score_dom, score_ext,
                   cote_1, cote_x, cote_2
            FROM matches 
            WHERE session_id = %s AND journee = %s 
            AND score_dom IS NOT NULL AND score_ext IS NOT NULL
        """, (session_id, journee))
        
        matches = cursor.fetchall()
        if not matches:
            return
        
        updates_count = 0
        for match in matches:
            dom_id = match['equipe_dom_id']
            ext_id = match['equipe_ext_id']
            score_dom = match['score_dom']
            score_ext = match['score_ext']
            
            # Déterminer le résultat
            if score_dom > score_ext:
                winner_id, loser_id = dom_id, ext_id
                result_type = 'HOME_WIN'
            elif score_ext > score_dom:
                winner_id, loser_id = ext_id, dom_id
                result_type = 'AWAY_WIN'
            else:
                # Match nul - ajustement mutuel
                _update_pair_strength(dom_id, ext_id, 'DRAW', match)
                _update_pair_strength(ext_id, dom_id, 'DRAW', match)
                updates_count += 2
                continue
            
            # Calculer les probabilités implicites des cotes
            cote_1 = float(match['cote_1'] or 2.0)
            cote_x = float(match['cote_x'] or 3.0)
            cote_2 = float(match['cote_2'] or 2.0)
            
            prob_home = 1.0 / cote_1 if cote_1 > 0 else 0.33
            prob_away = 1.0 / cote_2 if cote_2 > 0 else 0.33
            
            # Mettre à jour la paire vainqueur/perdant
            _update_pair_strength(winner_id, loser_id, result_type, match, prob_home if result_type == 'HOME_WIN' else prob_away)
            _update_pair_strength(loser_id, winner_id, 'LOSS', match, prob_home if result_type == 'HOME_WIN' else prob_away)
            updates_count += 2
        
        logger.info(f"[STRENGTH_MATRIX] J{journee}: {updates_count} relations mises à jour")
        save_matrix()
        
    except Exception as e:
        logger.error(f"[STRENGTH_MATRIX] Erreur mise à jour matrice: {e}")

def _update_pair_strength(team_id: int, opponent_id: int, result_type: str, match_data: dict, 
                       expected_prob: float = 0.5) -> None:
    """
    Met à jour la force d'une paire d'équipes avec lissage exponentiel.
    
    Args:
        team_id: Équipe dont on met à jour la force
        opponent_id: Adversaire
        result_type: 'HOME_WIN', 'AWAY_WIN', 'DRAW', 'LOSS'
        match_data: Données complètes du match
        expected_prob: Probabilité attendue selon les cotes
    """
    global _matrix
    
    if team_id not in _matrix or opponent_id not in _matrix[team_id]:
        return
    
    current_strength = _matrix[team_id][opponent_id]
    
    # Facteur d'apprentissage adaptatif selon résultat vs attente
    learning_rate = 0.15  # Base
    
    if result_type in ['HOME_WIN', 'AWAY_WIN']:
        # Victoire contre attente : ajustement positif
        outcome_bonus = 0.3 if expected_prob < 0.4 else 0.1
        learning_rate += outcome_bonus
    elif result_type == 'DRAW':
        # Match nul : ajustement neutre
        learning_rate = 0.08
    else:  # LOSS
        # Défaite : ajustement négatif
        outcome_penalty = -0.2 if expected_prob > 0.6 else -0.1
        learning_rate += outcome_penalty
    
    # Lissage exponentiel : nouvelle_valeur = ancienne * (1-α) + nouvelle * α
    if result_type in ['HOME_WIN', 'AWAY_WIN']:
        target_strength = min(2.0, current_strength + 0.2)  # Max 2.0
    elif result_type == 'DRAW':
        target_strength = max(0.5, min(1.5, current_strength))  # Range 0.5-1.5
    else:  # LOSS
        target_strength = max(0.3, current_strength - 0.15)  # Min 0.3
    
    # Application du lissage
    new_strength = (current_strength * (1 - abs(learning_rate))) + (target_strength * abs(learning_rate))
    new_strength = max(0.1, min(3.0, new_strength))  # Bornes de sécurité
    
    _matrix[team_id][opponent_id] = new_strength

def get_matrix_stats() -> dict:
    """Retourne des statistiques sur la matrice de force."""
    if not _matrix:
        return {'status': 'not_loaded'}
    
    all_values = []
    for team_id, opponents in _matrix.items():
        for opp_id, strength in opponents.items():
            if team_id != opp_id:
                all_values.append(strength)
    
    return {
        'status': 'loaded',
        'last_update': _last_update,
        'teams_count': len(_matrix),
        'total_pairs': len(all_values),
        'avg_strength': sum(all_values) / len(all_values) if all_values else 0,
        'min_strength': min(all_values) if all_values else 0,
        'max_strength': max(all_values) if all_values else 0,
        'std_strength': (sum((x - sum(all_values)/len(all_values))**2 for x in all_values) / len(all_values))**0.5 if all_values else 0
    }

def get_top_matchups(team_id: int, limit: int = 5) -> list:
    """Retourne les meilleurs match-ups pour une équipe donnée."""
    if team_id not in _matrix:
        return []
    
    matchups = [(opp_id, strength) for opp_id, strength in _matrix[team_id].items() if opp_id != team_id]
    matchups.sort(key=lambda x: x[1], reverse=True)
    
    return matchups[:limit]
