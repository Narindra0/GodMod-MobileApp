"""
FastAPI lightweight read-only API to expose GODMOD data to the mobile app.
Started automatically by Backend/main.py in a background thread.
"""

import os
import threading
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.core.database import get_db_connection
from src.core.session_manager import get_active_session
from src.core.team_utils import get_equipe_logo, get_toutes_les_equipes_avec_logos, get_match_with_logos


def _get_cors_origins() -> List[str]:
    """
    Read CORS origins from env var CORS_ORIGINS (comma separated),
    fallback to permissive for LAN testing.
    """
    env_val = os.getenv("CORS_ORIGINS")
    if env_val:
        return [o.strip() for o in env_val.split(",") if o.strip()]
    # Default: allow Expo LAN & localhost
    return [
        "http://localhost:19006",
        "http://localhost:8000",
        "http://127.0.0.1:19006",
        "http://127.0.0.1:8000",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ]


def create_app() -> FastAPI:
    app = FastAPI(title="GODMOD API", version="1.0.0", docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        session = get_active_session()
        return {
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": session["id"],
        }

    @app.get("/session/active")
    def session_active():
        session = get_active_session()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, current_day, capital_initial, score_prisma, score_zeus
                FROM sessions WHERE id = ?
                """,
                (session["id"],),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")

            # Bankroll = last bankroll_apres, fallback to capital_initial
            cursor.execute(
                """
                SELECT bankroll_apres FROM historique_paris
                WHERE session_id = ?
                ORDER BY id_pari DESC LIMIT 1
                """,
                (session["id"],),
            )
            bankroll_row = cursor.fetchone()
            bankroll = bankroll_row[0] if bankroll_row else row["capital_initial"]

            return {
                "id": row["id"],
                "current_day": row["current_day"],
                "capital_initial": row["capital_initial"],
                "score_prisma": row["score_prisma"],
                "score_zeus": row["score_zeus"],
                "bankroll": bankroll,
            }

    @app.get("/metrics/overview")
    def metrics_overview():
        session = get_active_session()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Total Win Rate & Predictions
            cursor.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN succes = 1 THEN 1 ELSE 0 END) as wins "
                "FROM predictions WHERE session_id = ?",
                (session["id"],),
            )
            total, wins = cursor.fetchone()
            win_rate = round((wins or 0) * 100 / total, 1) if total else 0.0

            # 2. Score IA & Capital Initial
            cursor.execute(
                "SELECT score_zeus, score_prisma, capital_initial FROM sessions WHERE id = ?", 
                (session["id"],)
            )
            row_session = cursor.fetchone()
            if not row_session:
                 return {
                    "win_rate": 0, "total_predictions": 0, "wins": 0,
                    "bankroll": 20000, "profit": 0, "score_ia": 0,
                    "bankroll_zeus": 20000, "bankroll_prisma": 20000
                }
            
            score_ia = (row_session["score_zeus"] or 0) + (row_session["score_prisma"] or 0)
            capital_initial = row_session["capital_initial"]

            # 3. Bankroll ZEUS
            cursor.execute(
                """
                SELECT bankroll_apres FROM historique_paris
                WHERE session_id = ? AND strategie = 'ZEUS'
                ORDER BY id_pari DESC LIMIT 1
                """,
                (session["id"],),
            )
            br_zeus_row = cursor.fetchone()
            bankroll_zeus = br_zeus_row[0] if br_zeus_row else capital_initial

            # 4. Bankroll PRISMA
            cursor.execute(
                """
                SELECT bankroll_apres FROM historique_paris
                WHERE session_id = ? AND strategie = 'PRISMA'
                ORDER BY id_pari DESC LIMIT 1
                """,
                (session["id"],),
            )
            br_prisma_row = cursor.fetchone()
            bankroll_prisma = br_prisma_row[0] if br_prisma_row else capital_initial

            # 5. Global Bankroll (last overall transaction)
            cursor.execute(
                """
                SELECT bankroll_apres FROM historique_paris
                WHERE session_id = ?
                ORDER BY id_pari DESC LIMIT 1
                """,
                (session["id"],),
            )
            br_row = cursor.fetchone()
            bankroll_global = br_row[0] if br_row else capital_initial

            profit = bankroll_global - capital_initial

            return {
                "win_rate": win_rate,
                "total_predictions": total or 0,
                "wins": wins or 0,
                "bankroll": bankroll_global,
                "profit": profit,
                "score_ia": score_ia,
                "bankroll_zeus": bankroll_zeus,
                "bankroll_prisma": bankroll_prisma
            }

    @app.get("/predictions/active")
    def predictions_active():
        session = get_active_session()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.id, m.journee, e1.nom as home, e2.nom as away,
                       p.prediction, p.fiabilite, p.resultat, p.succes,
                       m.status, m.cote_1, m.cote_x, m.cote_2
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE p.session_id = ? AND m.status = 'A_VENIR'
                ORDER BY m.journee ASC, m.id ASC
                """,
                (session["id"],),
            )
            rows = cursor.fetchall()
            return [_row_to_prediction_dict(r) for r in rows]

    @app.get("/predictions/history")
    def predictions_history(day: Optional[int] = None):
        session = get_active_session()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            params = [session["id"]]
            day_filter = ""
            if day is not None:
                day_filter = " AND m.journee = ? "
                params.append(day)

            cursor.execute(
                f"""
                SELECT p.id, m.journee, e1.nom as home, e2.nom as away,
                       p.prediction, p.fiabilite, p.resultat, p.succes,
                       m.status, m.cote_1, m.cote_x, m.cote_2
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE p.session_id = ? {day_filter} AND m.status = 'TERMINE'
                ORDER BY m.journee DESC, m.id DESC
                """,
                params,
            )
            rows = cursor.fetchall()
            return [_row_to_prediction_dict(r) for r in rows]

    @app.get("/matches/next")
    def next_match():
        session = get_active_session()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT m.id, m.journee, e1.nom as home, e2.nom as away,
                       m.cote_1, m.cote_x, m.cote_2, m.status
                FROM matches m
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE m.session_id = ? AND m.status = 'A_VENIR'
                ORDER BY m.journee ASC, m.id ASC
                LIMIT 1
                """,
                (session["id"],),
            )
            row = cursor.fetchone()
            if not row:
                return {}
            return {
                "id": row["id"],
                "journee": row["journee"],
                "home": row["home"],
                "away": row["away"],
                "cote_1": row["cote_1"],
                "cote_x": row["cote_x"],
                "cote_2": row["cote_2"],
                "status": row["status"],
            }

    @app.get("/standings")
    def standings():
        """
        Renvoie le classement le plus recent pour la session active.
        """
        session = get_active_session()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(journee) FROM classement WHERE session_id = ?",
                (session["id"],),
            )
            last_day = cursor.fetchone()[0]
            if not last_day:
                return []

            cursor.execute(
                """
                SELECT 
                    c.position,
                    c.points,
                    c.forme,
                    c.buts_pour,
                    c.buts_contre,
                    e.nom as team,
                    (
                        SELECT COUNT(*) 
                        FROM matches m 
                        WHERE m.session_id = c.session_id 
                          AND m.status = 'TERMINE'
                          AND (m.equipe_dom_id = c.equipe_id OR m.equipe_ext_id = c.equipe_id)
                    ) as played
                FROM classement c
                JOIN equipes e ON e.id = c.equipe_id
                WHERE c.session_id = ? AND c.journee = ?
                ORDER BY c.position ASC, e.nom ASC
                """,
                (session["id"], last_day),
            )
            rows = cursor.fetchall()
            return [
                {
                    "team": r["team"],
                    "points": r["points"],
                    "form": r["forme"],
                    "position": r["position"],
                    "played": r["played"],
                    "goals_for": r["buts_pour"],
                    "goals_against": r["buts_contre"],
                    "journee": last_day,
                }
                for r in rows
            ]

    # ===== ENDPOINTS POUR LES LOGOS D'ÉQUIPES =====
    
    @app.get("/teams/logos")
    def get_all_teams_logos():
        """Retourne toutes les équipes avec leurs logos"""
        try:
            equipes = get_toutes_les_equipes_avec_logos()
            return {
                "status": "success",
                "count": len(equipes),
                "teams": equipes
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/teams/{team_id}/logo")
    def get_team_logo(team_id: int):
        """Retourne le logo d'une équipe spécifique"""
        try:
            logo_url = get_equipe_logo(equipe_id=team_id)
            if logo_url:
                return {
                    "status": "success",
                    "team_id": team_id,
                    "logo_url": logo_url
                }
            else:
                raise HTTPException(status_code=404, detail="Logo not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/matches/{match_id}/logos")
    def get_match_logos(match_id: int):
        """Retourne les logos des deux équipes d'un match"""
        try:
            match_data = get_match_with_logos(match_id)
            if match_data:
                return {
                    "status": "success",
                    "match_id": match_id,
                    "equipe_dom": match_data["equipe_dom"],
                    "equipe_ext": match_data["equipe_ext"]
                }
            else:
                raise HTTPException(status_code=404, detail="Match not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app


def _row_to_prediction_dict(row):
    return {
        "id": row["id"],
        "journee": row["journee"],
        "home": row["home"],
        "away": row["away"],
        "prediction": row["prediction"],
        "fiabilite": row["fiabilite"],
        "resultat": row["resultat"],
        "succes": row["succes"],
        "status": row["status"],
        "cote_1": row["cote_1"],
        "cote_x": row["cote_x"],
        "cote_2": row["cote_2"],
    }


def start_api_server(host: str = "0.0.0.0", port: int = 8000):
    """
    Start uvicorn server in a daemon thread so it runs alongside monitoring.
    """
    import uvicorn

    app = create_app()

    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={
            "host": host,
            "port": port,
            "log_level": "info",
        },
        daemon=True,
        name="api-server",
    )
    server_thread.start()
    return server_thread
