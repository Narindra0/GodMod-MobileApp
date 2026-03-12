"""
Requêtes SQL sécurisées pour ZEUS avec isolation temporelle.
"""

import sqlite3
from typing import Dict, List, Optional, Tuple
import pandas as pd
from src.core.session_manager import get_active_session


def get_classement_snapshot(journee_actuelle: int, conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Récupère le classement AVANT le match day actuel pour la session active.
    """
    active_session = get_active_session()
    session_id = active_session['id']
    
    query = """
        SELECT 
            cg.equipe_id,
            cg.position,
            cg.points,
            cg.forme,
            e.nom as equipe_nom
        FROM classement cg
        JOIN equipes e ON cg.equipe_id = e.id
        WHERE cg.session_id = ? AND cg.journee = (
            SELECT MAX(journee) 
            FROM classement 
            WHERE session_id = ? AND journee < ?
        )
        ORDER BY cg.position
    """
    return pd.read_sql(query, conn, params=(session_id, session_id, journee_actuelle))


def _map_match_row(row) -> Dict:
    """Helper pour mapper une ligne de match vers un dictionnaire."""
    return {
        'id': row[0], 'journee': row[1], 'equipe_dom_id': row[2],
        'equipe_ext_id': row[3], 'equipe_dom_nom': row[4], 'equipe_ext_nom': row[5],
        'cote_1': row[6], 'cote_x': row[7], 'cote_2': row[8],
        'score_dom': row[9], 'score_ext': row[10], 'status': row[11]
    }


def get_match_data(match_id: int, conn: sqlite3.Connection) -> Optional[Dict]:
    """
    Récupère les données d'un match spécifique.
    """
    query = """
        SELECT 
            mg.id,
            mg.journee,
            mg.equipe_dom_id,
            mg.equipe_ext_id,
            e_dom.nom as equipe_dom_nom,
            e_ext.nom as equipe_ext_nom,
            mg.cote_1,
            mg.cote_x,
            mg.cote_2,
            mg.score_dom,
            mg.score_ext,
            mg.status
        FROM matches mg
        JOIN equipes e_dom ON mg.equipe_dom_id = e_dom.id
        JOIN equipes e_ext ON mg.equipe_ext_id = e_ext.id
        WHERE mg.id = ?
    """
    cursor = conn.cursor()
    cursor.execute(query, (match_id,))
    row = cursor.fetchone()
    
    return _map_match_row(row) if row else None


def get_matches_for_journee(journee: int, conn: sqlite3.Connection) -> List[Dict]:
    """
    Récupère tous les matchs d'une journée spécifique (toutes sessions confondues).
    """
    query = """
        SELECT 
            mg.id,
            mg.journee,
            mg.equipe_dom_id,
            mg.equipe_ext_id,
            e_dom.nom as equipe_dom_nom,
            e_ext.nom as equipe_ext_nom,
            mg.cote_1,
            mg.cote_x,
            mg.cote_2,
            mg.score_dom,
            mg.score_ext,
            mg.status
        FROM matches mg
        JOIN equipes e_dom ON mg.equipe_dom_id = e_dom.id
        JOIN equipes e_ext ON mg.equipe_ext_id = e_ext.id
        WHERE mg.journee = ?
        ORDER BY mg.id
    """
    cursor = conn.cursor()
    cursor.execute(query, (journee,))
    rows = cursor.fetchall()
    
    return [_map_match_row(row) for row in rows]


def create_session(
    capital_initial: int,
    type_session: str,
    version_ia: str,
    conn: sqlite3.Connection
) -> int:
    """
    Crée une nouvelle session ZEUS.
    Le score PRISMA est reporté de la dernière session active si possible.
    """
    cursor = conn.cursor()
    
    # Tenter de récupérer le dernier score PRISMA
    cursor.execute("SELECT score_prisma FROM sessions WHERE status = 'ACTIVE' LIMIT 1")
    row = cursor.fetchone()
    prisma_to_use = row[0] if row else 200
    
    cursor.execute("""
        INSERT INTO sessions (
            capital_initial,
            type_session,
            version_ia,
            score_zeus,
            score_prisma,
            status
        ) VALUES (?, ?, ?, 0, ?, 'ACTIVE')
    """, (capital_initial, type_session, version_ia, prisma_to_use))
    conn.commit()
    return cursor.lastrowid


def enregistrer_pari(
    session_id: int,
    prediction_id: int,
    journee: int,
    type_pari: str,
    mise_ar: int,
    pourcentage_bankroll: float,
    cote_jouee: Optional[float],
    resultat: Optional[int],
    profit_net: Optional[int],
    bankroll_apres: int,
    probabilite_implicite: Optional[float],
    action_id: int,
    conn: sqlite3.Connection
) -> int:
    """
    Enregistre un pari dans l'historique pour la session active.
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO historique_paris (
            session_id,
            prediction_id,
            journee,
            type_pari,
            mise_ar,
            pourcentage_bankroll,
            cote_jouee,
            resultat,
            profit_net,
            bankroll_apres,
            probabilite_implicite,
            action_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id, prediction_id, journee, type_pari, mise_ar,
        pourcentage_bankroll, cote_jouee, resultat, profit_net,
        bankroll_apres, probabilite_implicite, action_id
    ))
    conn.commit()
    return cursor.lastrowid


def finaliser_session(
    session_id: int,
    capital_final: int,
    profit_total: int,
    score_zeus: int,
    conn: sqlite3.Connection
):
    """
    Finalise une session avec les résultats finaux.
    
    Args:
        session_id: ID de la session
        capital_final: Capital final
        profit_total: Profit total (peut être négatif)
        score_zeus: Score final ZEUS (+1/-1 cumulatif)
        conn: Connexion SQLite
    """
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET timestamp_fin = CURRENT_TIMESTAMP,
            capital_final = ?,
            profit_total = ?,
            score_zeus = ?
        WHERE session_id = ?
    """, (capital_final, profit_total, score_zeus, session_id))
    conn.commit()


def get_available_seasons(conn: sqlite3.Connection) -> List[int]:
    """
    Récupère la liste des saisons disponibles à partir de TOUTES les sessions.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT journee 
        FROM matches 
        WHERE status = 'TERMINE'
        ORDER BY journee
    """)
    all_journees = [row[0] for row in cursor.fetchall()]
    
    # Grouper par début de saisons réelles (tous les 38 jours)
    seasons = []
    if all_journees:
        # On considère une saison disponible si on a son premier jour
        for j in all_journees:
            if (j - 1) % 38 == 0:
                seasons.append(j)
    
    return seasons


def get_last_training_metadata(conn: sqlite3.Connection) -> Dict:
    """
    Récupère les métadonnées de la dernière session d'entraînement réussie.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT version_ia, MAX(journee) as max_j, session_id
        FROM sessions
        WHERE type_session = 'TRAINING' AND timestamp_fin IS NOT NULL
        ORDER BY session_id DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    if row:
        return {'version': row[0], 'max_journee': row[1] if row[1] else 0, 'id': row[2]}
    return {'version': 'v0', 'max_journee': 0, 'id': None}


def get_completed_journees_count(conn: sqlite3.Connection) -> int:
    """
    Retourne la dernière journée complétée pour la session active.
    """
    session_id = get_active_session()['id']
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(journee) FROM matches WHERE status = 'TERMINE' AND session_id = ?", (session_id,))
    row = cursor.fetchone()
    return row[0] if row[0] else 0


def check_new_season_available(conn: sqlite3.Connection) -> bool:
    """
    Vérifie si une nouvelle saison complète (38 j) est disponible depuis le dernier entraînement.
    """
    last_meta = get_last_training_metadata(conn)
    current_max = get_completed_journees_count(conn)
    
    # Si on a au moins 38 journées de plus que le dernier entraînement
    return (current_max - last_meta['max_journee']) >= 38
