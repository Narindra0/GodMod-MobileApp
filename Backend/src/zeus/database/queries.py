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
    Récupère tous les matchs d'une journée spécifique pour la session active uniquement.
    """
    active_session = get_active_session()
    session_id = active_session['id']
    
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
        WHERE mg.journee = ? AND mg.session_id = ?
        ORDER BY mg.id
    """
    cursor = conn.cursor()
    cursor.execute(query, (journee, session_id))
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
    """
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET timestamp_fin = CURRENT_TIMESTAMP,
            capital_final = ?,
            profit_total = ?,
            score_zeus = ?
        WHERE id = ?
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
    
    seasons = []
    if all_journees:
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
        SELECT s.version_ia, MAX(m.journee) as max_j, s.id
        FROM sessions s
        LEFT JOIN matches m ON s.id = m.session_id
        WHERE s.type_session = 'TRAINING' AND s.timestamp_fin IS NOT NULL
        GROUP BY s.id
        ORDER BY s.id DESC
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
    
    return (current_max - last_meta['max_journee']) >= 38


def valider_paris_zeus(conn: sqlite3.Connection):
    """
    Vérifie les matchs terminés pour les paris ZEUS et calcule les profits/pertes.
    """
    cursor = conn.cursor()
    
    query = """
        SELECT 
            hp.id_pari,
            hp.prediction_id,
            hp.type_pari,
            hp.mise_ar,
            hp.cote_jouee,
            hp.session_id,
            m.score_dom,
            m.score_ext,
            m.status
        FROM historique_paris hp
        JOIN predictions p ON hp.prediction_id = p.id
        JOIN matches m ON p.match_id = m.id
        WHERE hp.resultat IS NULL AND hp.strategie = 'ZEUS' AND m.status = 'TERMINE'
    """
    cursor.execute(query)
    paris_en_attente = cursor.fetchall()
    
    if not paris_en_attente:
        return

    sessions_to_update = set(p['session_id'] for p in paris_en_attente)
    
    for sess_id in sessions_to_update:
        cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = ? AND strategie = 'ZEUS' AND resultat IS NOT NULL ORDER BY id_pari DESC LIMIT 1", (sess_id,))
        row = cursor.fetchone()
        
        if not row:
            cursor.execute("SELECT capital_initial FROM sessions WHERE id = ?", (sess_id,))
            row_sess = cursor.fetchone()
            current_bankroll = row_sess[0] if row_sess else 20000
        else:
            current_bankroll = row[0]

        p_sess = [p for p in paris_en_attente if p['session_id'] == sess_id]
        
        for p in p_sess:
            is_win = False
            sd, se = p['score_dom'], p['score_ext']
            
            if sd is None or se is None:
                continue

            recorded_type = p['type_pari']
            
            if recorded_type == '1' and sd > se: is_win = True
            elif recorded_type in ('X', 'N') and sd == se: is_win = True
            elif recorded_type == '2' and se > sd: is_win = True
            
            if is_win:
                profit_net = int(p['mise_ar'] * (p['cote_jouee'] - 1))
                resultat_val = 1
            else:
                profit_net = -p['mise_ar']
                resultat_val = 0
            
            current_bankroll += profit_net
            
            cursor.execute("""
                UPDATE historique_paris 
                SET resultat = ?, profit_net = ?, bankroll_apres = ?
                WHERE id_pari = ?
            """, (resultat_val, profit_net, current_bankroll, p['id_pari']))
            
            delta_score = 1 if is_win else -1
            cursor.execute("UPDATE sessions SET score_zeus = score_zeus + ? WHERE id = ?", (delta_score, sess_id))
            
    conn.commit()
    print(f"✅ {len(paris_en_attente)} paris ZEUS validés.")
