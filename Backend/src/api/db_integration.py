"""
Module d'integration de l'API avec la base de donnees existante
Utilise la structure BDD actuelle sans modification

Version: 2.1
Date: Janvier 2025
"""

import sqlite3
import logging
from typing import List, Dict, Tuple
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.database import get_db_connection
from src.core import config
from src.core.session_manager import get_active_session, update_session_day

logger = logging.getLogger(__name__)

def normalize_team_name(team_name: str) -> str:
    """
    Normalise le nom d'equipe en utilisant les alias du config
    
    Args:
        team_name: Nom de l'equipe depuis l'API
        
    Returns:
        Nom normalise pour la BDD
    """
    return config.TEAM_ALIASES.get(team_name, team_name)

def normalize_form_history(history: List[str]) -> str:
    """
    Convertit l'historique API (Won, Lost, Draw) en format BDD (V, D, N)
    Ex: ['Won', 'Draw', 'Lost'] -> "V,N,D"
    """
    mapping = {
        'Won': 'V',
        'Lost': 'D',
        'Draw': 'N'
    }
    
    normalized = [mapping.get(res, '?') for res in history[-5:]]
    return "".join(normalized)


def insert_api_ranking(ranking_data: List[Dict], session_id: int = None) -> int:
    """
    Insere le classement depuis l'API dans la table 'classement'
    
    Args:
        ranking_data: Liste des equipes avec leurs statistiques
        session_id: ID de la session (optionnel, utilise la session active par défaut)
        
    Returns:
        Nombre d'equipes inserees
    """
    if not ranking_data:
        logger.warning("Aucune donnee de classement a inserer")
        return 0
    
    journee = ranking_data[0].get("won", 0) + ranking_data[0].get("lost", 0) + ranking_data[0].get("draw", 0)
    
    if journee == 38:
        logger.info("Exception J38 détectée dans le classement. Données ignorées.")
        return 0
    
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session['id']
        current_day = active_session['current_day']

        if journee < current_day:
            logger.warning(f"Classement journee {journee} ignoré (BDD à J{current_day})")
            return 0
        if journee > current_day + 1:
            logger.warning(f"Classement journee {journee} en avance (> +1). Ignoré pour éviter la désync.")
            return 0

        if active_session['current_day'] != journee:
            active_session = update_session_day(session_id, journee)
            session_id = active_session['id']

    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM classement WHERE session_id = ? AND journee = ?", (session_id, journee))
        
        for team in ranking_data:
            team_name = normalize_team_name(team.get("name"))
            position = team.get("position")
            points = team.get("points")
            
            history = team.get("history", [])
            forme = normalize_form_history(history)
            
            cursor.execute("SELECT id FROM equipes WHERE nom = ?", (team_name,))
            result = cursor.fetchone()
            
            if result:
                equipe_id = result[0]
                
                cursor.execute("""
                    SELECT 
                        SUM(CASE WHEN equipe_dom_id = ? THEN score_dom ELSE score_ext END) as bp,
                        SUM(CASE WHEN equipe_dom_id = ? THEN score_ext ELSE score_dom END) as bc
                    FROM matches 
                    WHERE session_id = ? AND (equipe_dom_id = ? OR equipe_ext_id = ?) AND score_dom IS NOT NULL
                """, (equipe_id, equipe_id, session_id, equipe_id, equipe_id))
                stats_buts = cursor.fetchone()
                buts_pour = stats_buts[0] if stats_buts and stats_buts[0] is not None else 0
                buts_contre = stats_buts[1] if stats_buts and stats_buts[1] is not None else 0
                
                cursor.execute("""
                    INSERT INTO classement (session_id, journee, equipe_id, position, points, forme, buts_pour, buts_contre)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (session_id, journee, equipe_id, position, points, forme, buts_pour, buts_contre))
                
                count += 1
            else:
                logger.warning(f"Equipe '{team_name}' non trouvee dans la BDD")
    
    logger.info(f"{count} equipes inserees dans le classement (journee {journee}) avec stats buts")
    return count


def insert_api_results(results_data: List[Dict], session_id: int = None) -> Tuple[int, int]:
    """
    Insere les resultats depuis l'API dans la table 'matches'
    
    Args:
        results_data: Liste des journees avec leurs matchs
        session_id: ID de la session (optionnel)
        
    Returns:
        Nombre de matchs inseres
    """
    if not results_data:
        logger.warning("Aucun resultat a inserer")
        return 0, 0
    
    count = 0
    validated_count = 0
    
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session['id']
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        for round_data in results_data:
            journee = round_data.get("roundNumber")
            
            if journee == 38:
                continue
                
            for match in round_data.get("matches", []):
                home_team = normalize_team_name(match.get("homeTeam"))
                away_team = normalize_team_name(match.get("awayTeam"))
                score = match.get("score", "")
                
                if score and ":" in score:
                    parts = score.split(":")
                    score_dom = int(parts[0])
                    score_ext = int(parts[1])
                else:
                    score_dom = None
                    score_ext = None
                
                cursor.execute("SELECT id FROM equipes WHERE nom = ?", (home_team,))
                home_result = cursor.fetchone()
                cursor.execute("SELECT id FROM equipes WHERE nom = ?", (away_team,))
                away_result = cursor.fetchone()
                
                if home_result and away_result:
                    home_id = home_result[0]
                    away_id = away_result[0]
                    
                    cursor.execute("""
                        UPDATE matches 
                        SET score_dom = ?, score_ext = ?, status = 'TERMINE'
                        WHERE session_id = ? AND journee = ? AND equipe_dom_id = ? AND equipe_ext_id = ?
                    """, (score_dom, score_ext, session_id, journee, home_id, away_id))
                    
                    if cursor.rowcount == 0:
                        cursor.execute("""
                            INSERT INTO matches (session_id, journee, equipe_dom_id, equipe_ext_id, score_dom, score_ext, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'TERMINE')
                        """, (session_id, journee, home_id, away_id, score_dom, score_ext))
                    else:
                        validated_count += 1
                    
                    count += 1
                else:
                    logger.warning(f"Equipes non trouvees: {home_team} vs {away_team}")
    
    logger.info(f"{count} resultats inseres/mis-a-jour, {validated_count} valides (sans changement)")
    return count, validated_count


def insert_api_matches(matches_data: List[Dict], session_id: int = None) -> int:
    """
    Insere les matchs a venir depuis l'API dans la table 'matches'
    
    Args:
        matches_data: Liste des journees avec leurs matchs et cotes
        session_id: ID de la session (optionnel)
        
    Returns:
        Nombre de matchs inseres
    """
    if not matches_data:
        logger.warning("Aucun match a venir a inserer")
        return 0
    
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session['id']
    
    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        for round_data in matches_data:
            journee = round_data.get("roundNumber")
            
            if journee == 38:
                continue
                
            for match in round_data.get("matches", []):
                home_team = normalize_team_name(match.get("homeTeam"))
                away_team = normalize_team_name(match.get("awayTeam"))
                odds = match.get("odds", [])
                
                cote_1 = next((o["odds"] for o in odds if o["type"] == "1"), None)
                cote_x = next((o["odds"] for o in odds if o["type"] == "X"), None)
                cote_2 = next((o["odds"] for o in odds if o["type"] == "2"), None)
                
                cursor.execute("SELECT id FROM equipes WHERE nom = ?", (home_team,))
                home_result = cursor.fetchone()
                cursor.execute("SELECT id FROM equipes WHERE nom = ?", (away_team,))
                away_result = cursor.fetchone()
                
                if home_result and away_result:
                    home_id = home_result[0]
                    away_id = away_result[0]
                    
                    cursor.execute("""
                        INSERT INTO matches (session_id, journee, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'A_VENIR')
                        ON CONFLICT(session_id, journee, equipe_dom_id, equipe_ext_id) DO UPDATE SET
                            cote_1 = excluded.cote_1,
                            cote_x = excluded.cote_x,
                            cote_2 = excluded.cote_2
                    """, (session_id, journee, home_id, away_id, cote_1, cote_x, cote_2))
                    
                    count += 1
                else:
                    logger.warning(f"Equipes non trouvees: {home_team} vs {away_team}")
    
    logger.info(f"{count} matchs a venir inseres avec leurs cotes")
    return count
