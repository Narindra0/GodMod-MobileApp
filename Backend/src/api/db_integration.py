import logging
import os
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core import config
from core.database import get_db_connection
from core.session_manager import get_active_session, update_session_day

logger = logging.getLogger(__name__)


def normalize_team_name(team_name: str) -> str:
    return config.TEAM_ALIASES.get(team_name, team_name)


def normalize_form_history(history: List[str]) -> str:
    mapping = {"Won": "V", "Lost": "D", "Draw": "N"}
    normalized = [mapping.get(res, "?") for res in history[-5:]]
    return "".join(normalized)


def insert_api_ranking(ranking_data: List[Dict], session_id: int = None) -> int:
    if not ranking_data:
        logger.warning("Aucune donnee de classement a inserer")
        return 0
    journee = ranking_data[0].get("won", 0) + ranking_data[0].get("lost", 0) + ranking_data[0].get("draw", 0)
    if journee == 38:
        logger.info("Exception J38 détectée dans le classement. Données ignorées.")
        return 0
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session["id"]
        current_day = active_session["current_day"]
        if journee < current_day:
            logger.warning(f"Classement journee {journee} ignoré (BDD à J{current_day})")
            return 0
        if journee > current_day + 1:
            logger.warning(f"Classement journee {journee} en avance (> +1). Ignoré pour éviter la désync.")
            return 0
    # Pre-fetch team IDs to avoid queries in loop
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Fix #8 : Mise à jour du current_day DANS le même bloc de connexion
        # pour éviter une race condition. Uniquement si session_id vient de l'interne
        # (non passé explicitement par l'appelant, ex: collect_full_data)
        current_session = get_active_session(conn=conn)
        if current_session["id"] == session_id and current_session["current_day"] != journee:
            cursor.execute(
                "UPDATE sessions SET current_day = %s WHERE id = %s",
                (journee, session_id)
            )
            logger.info(f"Session {session_id} mise à jour au jour {journee} (atomique avec classement)")

        cursor.execute("SELECT nom, id FROM equipes")
        equipes_map = {row["nom"]: row["id"] for row in cursor.fetchall()}

        cursor.execute("DELETE FROM classement WHERE session_id = %s AND journee = %s", (session_id, journee))

        # Calcul agrégé des buts (pour/contre) par équipe sur toute la session.
        # Buts_pour = score du côté où l'équipe joue (dom: score_dom, ext: score_ext)
        # Buts_contre = score de l'adversaire correspondant (dom: score_ext, ext: score_dom)
        cursor.execute(
            """
            SELECT
                team_id,
                COALESCE(SUM(bp), 0) AS bp,
                COALESCE(SUM(bc), 0) AS bc
            FROM (
                SELECT
                    equipe_dom_id AS team_id,
                    score_dom AS bp,
                    score_ext AS bc
                FROM matches
                WHERE session_id = %s AND score_dom IS NOT NULL AND score_ext IS NOT NULL
                UNION ALL
                SELECT
                    equipe_ext_id AS team_id,
                    score_ext AS bp,
                    score_dom AS bc
                FROM matches
                WHERE session_id = %s AND score_dom IS NOT NULL AND score_ext IS NOT NULL
            ) t
            GROUP BY team_id
            """,
            (session_id, session_id),
        )
        stats_by_team = {
            row["team_id"]: {"bp": row["bp"], "bc": row["bc"]}
            for row in cursor.fetchall()
        }

        insert_data = []
        for team in ranking_data:
            team_name = normalize_team_name(team.get("name"))
            equipe_id = equipes_map.get(team_name)

            if equipe_id:
                position = team.get("position")
                points = team.get("points")
                forme = normalize_form_history(team.get("history", []))
                stats_buts = stats_by_team.get(equipe_id, {"bp": 0, "bc": 0})
                buts_pour = stats_buts["bp"] if stats_buts and stats_buts.get("bp") is not None else 0
                buts_contre = stats_buts["bc"] if stats_buts and stats_buts.get("bc") is not None else 0

                insert_data.append((session_id, journee, equipe_id, position, points, forme, buts_pour, buts_contre))
            else:
                logger.warning(f"Equipe '{team_name}' non trouvee dans la BDD")

        count = 0
        if insert_data:
            cursor.executemany(
                """
                INSERT INTO classement (session_id, journee, equipe_id, position, points, forme, buts_pour, buts_contre)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
                insert_data,
            )
            count = len(insert_data)

    logger.info(f"{count} equipes inserees dans le classement (journee {journee}) avec stats buts")
    return count


def insert_api_results(results_data: List[Dict], session_id: int = None) -> Tuple[int, int]:
    if not results_data:
        logger.warning("Aucun resultat a inserer")
        return 0, 0
    count = 0
    validated_count = 0
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session["id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nom, id FROM equipes")
        equipes_map = {row["nom"]: row["id"] for row in cursor.fetchall()}

        for round_data in results_data:
            journee = round_data.get("roundNumber")
            if journee == 38:
                continue
            for match in round_data.get("matches", []):
                home_team = normalize_team_name(match.get("homeTeam"))
                away_team = normalize_team_name(match.get("awayTeam"))
                home_id = equipes_map.get(home_team)
                away_id = equipes_map.get(away_team)

                if home_id and away_id:
                    score = match.get("score", "")
                    if score and ":" in score:
                        parts = score.split(":")
                        score_dom = int(parts[0])
                        score_ext = int(parts[1])
                    else:
                        score_dom = None
                        score_ext = None

                    cursor.execute(
                        """
                        UPDATE matches
                        SET score_dom = %s, score_ext = %s, status = 'TERMINE'
                        WHERE session_id = %s AND journee = %s AND equipe_dom_id = %s AND equipe_ext_id = %s
                    """,
                        (score_dom, score_ext, session_id, journee, home_id, away_id),
                    )

                    if cursor.rowcount == 0:
                        cursor.execute(
                            """
                            INSERT INTO matches (session_id, journee, equipe_dom_id, 
                            equipe_ext_id, score_dom, score_ext, status)
                            VALUES (%s, %s, %s, %s, %s, %s, 'TERMINE')
                        """,
                            (session_id, journee, home_id, away_id, score_dom, score_ext),
                        )
                    else:
                        validated_count += 1
                    count += 1
                else:
                    logger.warning(f"Equipes non trouvees: {home_team} vs {away_team}")
    logger.info(f"{count} resultats inseres/mis-a-jour, {validated_count} valides (sans changement)")
    return count, validated_count


def insert_api_matches(matches_data: List[Dict], session_id: int = None) -> int:
    if not matches_data:
        logger.warning("Aucun match a venir a inserer")
        return 0
    if session_id is None:
        active_session = get_active_session()
        session_id = active_session["id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nom, id FROM equipes")
        equipes_map = {row["nom"]: row["id"] for row in cursor.fetchall()}

        insert_data = []
        for round_data in matches_data:
            journee = round_data.get("roundNumber")
            if journee == 38:
                continue
            for match in round_data.get("matches", []):
                home_team = normalize_team_name(match.get("homeTeam"))
                away_team = normalize_team_name(match.get("awayTeam"))
                home_id = equipes_map.get(home_team)
                away_id = equipes_map.get(away_team)

                if home_id and away_id:
                    odds = match.get("odds", [])
                    cote_1 = next((o["odds"] for o in odds if o["type"] == "1"), None)
                    cote_x = next((o["odds"] for o in odds if o["type"] == "X"), None)
                    cote_2 = next((o["odds"] for o in odds if o["type"] == "2"), None)

                    insert_data.append((session_id, journee, home_id, away_id, cote_1, cote_x, cote_2))
                else:
                    logger.warning(f"Equipes non trouvees: {home_team} vs {away_team}")

        count = 0
        if insert_data:
            cursor.executemany(
                """
                INSERT INTO matches (session_id, journee, equipe_dom_id, equipe_ext_id, cote_1, cote_x, cote_2, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'A_VENIR')
                ON CONFLICT(session_id, journee, equipe_dom_id, equipe_ext_id) DO UPDATE SET
                    cote_1 = excluded.cote_1,
                    cote_x = excluded.cote_x,
                    cote_2 = excluded.cote_2
            """,
                insert_data,
            )
            count = len(insert_data)

    logger.info(f"{count} matchs a venir inseres avec leurs cotes")
    return count
