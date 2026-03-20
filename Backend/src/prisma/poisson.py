"""
PRISMA Poisson Distribution Module
Calcul des probabilités de score exact et validation des prédictions via la loi de Poisson.
"""
import logging
import numpy as np
from scipy.stats import poisson
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

def get_league_averages(conn, session_id: int) -> Tuple[float, float]:
    """
    Calcule les moyennes de buts (domicile/extérieur) pour la session actuelle.
    """
    cursor = conn.cursor()
    query = """
        SELECT 
            AVG(score_dom) as avg_home,
            AVG(score_ext) as avg_away,
            COUNT(*) as match_count
        FROM matches 
        WHERE session_id = %s AND score_dom IS NOT NULL AND score_ext IS NOT NULL
    """
    cursor.execute(query, (session_id,))
    row = cursor.fetchone()
    
    if not row or not row['match_count'] or row['match_count'] < 10:
        # Fallback si pas assez de données (moyennes typiques)
        return 1.5, 1.2
        
    return float(row['avg_home']), float(row['avg_away'])

def calculate_team_strengths(conn, session_id: int):
    """
    Calcule l'Attaque et la Défense relative de chaque équipe.
    """
    avg_home, avg_away = get_league_averages(conn, session_id)
    cursor = conn.cursor()
    
    # Force d'attaque et défense à domicile
    query_home = """
        SELECT 
            equipe_dom_id as equipe_id,
            AVG(score_dom) as scored_avg,
            AVG(score_ext) as conceded_avg,
            COUNT(*) as games
        FROM matches 
        WHERE session_id = %s AND score_dom IS NOT NULL
        GROUP BY equipe_dom_id
    """
    cursor.execute(query_home, (session_id,))
    home_stats = {row['equipe_id']: row for row in cursor.fetchall()}
    
    # Force d'attaque et défense à l'extérieur
    query_away = """
        SELECT 
            equipe_ext_id as equipe_id,
            AVG(score_ext) as scored_avg,
            AVG(score_dom) as conceded_avg,
            COUNT(*) as games
        FROM matches 
        WHERE session_id = %s AND score_ext IS NOT NULL
        GROUP BY equipe_ext_id
    """
    cursor.execute(query_away, (session_id,))
    away_stats = {row['equipe_id']: row for row in cursor.fetchall()}
    
    strengths = {}
    
    # On itère sur toutes les équipes de la session (depuis classement par exemple)
    cursor.execute("SELECT id FROM equipes")
    for eq in cursor.fetchall():
        eid = eq['id']
        h = home_stats.get(eid, {'scored_avg': avg_home, 'conceded_avg': avg_away, 'games': 0})
        a = away_stats.get(eid, {'scored_avg': avg_away, 'conceded_avg': avg_home, 'games': 0})
        
        # Calcul des ratios (Force)
        # Plus c'est élevé, plus l'attaque est forte (>1.0) ou la défense est faible (>1.0)
        strengths[eid] = {
            'home_attack': float(h['scored_avg']) / avg_home if avg_home > 0 else 1.0,
            'home_defense': float(h['conceded_avg']) / avg_away if avg_away > 0 else 1.0,
            'away_attack': float(a['scored_avg']) / avg_away if avg_away > 0 else 1.0,
            'away_defense': float(a['conceded_avg']) / avg_home if avg_home > 0 else 1.0
        }
        
    return strengths, avg_home, avg_away

def predict_score_probs(home_id: int, away_id: int, conn, session_id: int, max_goals: int = 5):
    """
    Prédit les probabilités de score pour un match.
    """
    strengths, league_home_avg, league_away_avg = calculate_team_strengths(conn, session_id)
    
    if home_id not in strengths or away_id not in strengths:
        return None

    # Calcul des espérances de buts (Lambdas)
    s_home = strengths[home_id]
    s_away = strengths[away_id]
    
    lambda_home = s_home['home_attack'] * s_away['away_defense'] * league_home_avg
    lambda_away = s_away['away_attack'] * s_home['home_defense'] * league_away_avg
    
    # Matrice de probabilités
    prob_matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            prob_matrix[i, j] = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)
            
    # Calcul des issues 1X2
    p_home = np.sum(np.tril(prob_matrix, -1)) # Somme de la partie triangulaire inférieure (i > j)
    # Ah non, attention: tril avec -1 donne les éléments SOUS la diagonale
    # i est Home, j est Away.
    # Matrice: rows=Home goals, columns=Away goals
    # [0,0] [0,1] [0,2] ...
    # [1,0] [1,1] [1,2] ...
    # [2,0] [2,1] [2,2] ...
    
    # Home gagne si i > j (partie SOUS la diagonale)
    p_home = 0
    p_draw = 0
    p_away = 0
    
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            if i > j: p_home += prob_matrix[i, j]
            elif i == j: p_draw += prob_matrix[i, j]
            else: p_away += prob_matrix[i, j]
            
    # Normalisation pour que la somme soit 1.0 (malgré max_goals)
    total = p_home + p_draw + p_away
    if total > 0:
        p_home /= total
        p_draw /= total
        p_away /= total
        
    # Score le plus probable
    max_idx = np.unravel_index(np.argmax(prob_matrix), prob_matrix.shape)
    
    return {
        'probabilities': {'1': float(p_home), 'X': float(p_draw), '2': float(p_away)},
        'most_likely_score': f"{max_idx[0]}-{max_idx[1]}",
        'lambda_home': float(lambda_home),
        'lambda_away': float(lambda_away)
    }
