import os
import threading
import uvicorn
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Query, HTTPException, Body
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from src.core.database import get_db_connection  # Import direct PostgreSQL
from src.core.session_manager import get_active_session
from src.core import config
from src.core.init_data import initialize_all
import json
import logging

logger = logging.getLogger("server")

# Pydantic models
class ResetRequest(BaseModel):
    confirmation: str

class AiSettingsUpdate(BaseModel):
    enabled: bool

class BorrowRequest(BaseModel):
    amount: int

class OverrideRequest(BaseModel):
    session_id: int
    override: bool

def _get_cors_origins() -> List[str]:
    env_val = os.getenv("CORS_ORIGINS")
    if env_val:
        return [o.strip() for o in env_val.split(",") if o.strip()]
    return [
        "http://localhost:19006",
        "http://localhost:8000",
        "http://127.0.0.1:19006",
        "http://127.0.0.1:8000",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ]

def create_app() -> FastAPI:
    # Initialisation des données au démarrage
    initialize_all()
    
    app = FastAPI(title="GODMOD API", version="1.0.0", docs_url="/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Enregistrer les routes
    register_routes(app)
    
    return app

def get_prisma_bankroll():
    """Read PRISMA bankroll from database via prisma_finance"""
    try:
        from src.core.prisma_finance import get_prisma_bankroll as get_bankroll_from_core
        return get_bankroll_from_core()
    except Exception as e:
        logger.error(f"Error reading PRISMA bankroll: {e}")
        return 20000  # Fallback value

def register_routes(app: FastAPI):
    @app.get("/health")
    async def health():
        try:
            active_session = get_active_session()
            return {"status": "ok", "session_id": active_session['id']}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/settings/ai")
    async def get_ai_settings():
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT value_int FROM prisma_config WHERE key = 'ai_enabled'")
                    row = cur.fetchone()
                    ai_enabled = bool(row['value_int']) if row and row['value_int'] is not None else True
                    return {"enabled": ai_enabled}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.post("/settings/ai")
    async def toggle_ai_settings(settings: AiSettingsUpdate):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    val = 1 if settings.enabled else 0
                    cur.execute(
                        "INSERT INTO prisma_config (key, value_int) VALUES ('ai_enabled', %s) "
                        "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int",
                        (val,)
                    )
                    conn.commit()
                    return {"status": "success", "enabled": settings.enabled}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.post("/zeus/borrow")
    async def zeus_borrow(request: BorrowRequest):
        try:
            active_session = get_active_session()
            session_id = active_session['id']
            with get_db_connection(write=True) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE sessions 
                    SET dette_zeus = dette_zeus + %s,
                        total_emprunte_zeus = total_emprunte_zeus + %s
                    WHERE id = %s
                """, (request.amount, request.amount, session_id))
                
                cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = %s AND strategie = 'ZEUS' ORDER BY id_pari DESC LIMIT 1", (session_id,))
                row = cursor.fetchone()
                current_bankroll = row['bankroll_apres'] if row else active_session['capital_initial']
                new_bankroll = current_bankroll + request.amount
                
                cursor.execute("""
                    INSERT INTO historique_paris (
                        session_id, prediction_id, journee, type_pari, 
                        mise_ar, profit_net, bankroll_apres, strategie, action_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (session_id, None, 0, 'EMPRUNT', 0, request.amount, new_bankroll, 'ZEUS', 0))
                
                conn.commit()
                return {"status": "success", "new_bankroll": new_bankroll, "debt": request.amount}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur emprunt: {str(e)}")

    @app.get("/metrics/overview")
    async def get_metrics_overview():
        try:
            active_session = get_active_session()
            session_id = active_session['id']
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM predictions WHERE session_id = %s AND succes IS NOT NULL", (session_id,))
                total = cursor.fetchone()['count']
                cursor.execute("SELECT COUNT(*) FROM predictions WHERE session_id = %s AND succes = 1", (session_id,))
                wins = cursor.fetchone()['count']
                win_rate = (wins / total * 100) if total > 0 else 0

                cursor.execute("""
                    SELECT bankroll_apres FROM historique_paris 
                    WHERE session_id = %s AND (strategie = 'ZEUS' OR strategie IS NULL)
                    ORDER BY id_pari DESC LIMIT 1
                """, (session_id,))
                row_zeus = cursor.fetchone()
                bankroll_zeus = row_zeus['bankroll_apres'] if row_zeus else active_session['capital_initial']
                
                bankroll_prisma = get_prisma_bankroll()
                
                profit_zeus = bankroll_zeus - active_session['capital_initial']
                profit_prisma = bankroll_prisma - 20000 
                total_profit = profit_zeus + profit_prisma

                cursor.execute("SELECT score_prisma, score_zeus, dette_zeus, total_emprunte_zeus, stop_loss_override FROM sessions WHERE id = %s", (session_id,))
                session_data = cursor.fetchone()
                score_prisma = session_data['score_prisma'] if session_data else 0
                score_zeus = session_data['score_zeus'] if session_data else 0
                dette_zeus = session_data['dette_zeus'] if session_data else 0
                total_emprunte = session_data['total_emprunte_zeus'] if session_data else 0
                override = session_data['stop_loss_override'] if session_data else False

                return {
                    "session_id": session_id,
                    "win_rate": round(win_rate, 1),
                    "total_predictions": total,
                    "wins": wins,
                    "bankroll": bankroll_zeus,
                    "profit": total_profit,
                    "score_ia": score_prisma + score_zeus,
                    "bankroll_zeus": bankroll_zeus,
                    "bankroll_prisma": bankroll_prisma,
                    "dette_zeus": dette_zeus,
                    "total_emprunte": total_emprunte,
                    "stop_loss_override": override
                }
        except Exception as e:
            logger.error(f"Error fetching metrics: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/predictions/active")
    async def get_active_predictions():
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, m.journee, e1.nom as home, e1.logo_url as home_logo, 
                       e2.nom as away, e2.logo_url as away_logo, 
                       p.prediction, p.fiabilite, p.succes, m.status,
                       m.cote_1, m.cote_x, m.cote_2, p.source,
                       gb.boost as ia_boost, gb.raison as ia_raison
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                LEFT JOIN groq_boosts gb ON p.session_id = gb.session_id AND m.journee = gb.journee AND m.equipe_dom_id = gb.equipe_dom_id AND m.equipe_ext_id = gb.equipe_ext_id
                WHERE p.session_id = %s AND p.succes IS NULL
                AND p.id NOT IN (
                    SELECT pmi.prediction_id 
                    FROM pari_multiple_items pmi
                    JOIN pari_multiple pm ON pmi.pari_multiple_id = pm.id
                    WHERE pm.session_id = %s AND pm.resultat IS NULL
                )
                ORDER BY m.journee DESC
            """, (session_id, session_id))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    @app.get("/predictions/combo")
    async def get_combo_predictions():
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, journee, mise_ar, cote_totale
                FROM pari_multiple
                WHERE session_id = %s AND resultat IS NULL
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            combo_row = cursor.fetchone()
            if not combo_row:
                return {}

            combo_id = combo_row['id']
            cursor.execute("""
                SELECT p.id, m.journee, e1.nom as home, e2.nom as away, 
                       p.prediction, p.fiabilite, p.source,
                       CASE 
                           WHEN p.prediction = '1' THEN m.cote_1
                           WHEN p.prediction = 'X' THEN m.cote_x
                           WHEN p.prediction = '2' THEN m.cote_2
                       END as cote,
                       gb.boost as ia_boost, gb.raison as ia_raison
                FROM pari_multiple_items pmi
                JOIN predictions p ON pmi.prediction_id = p.id
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                LEFT JOIN groq_boosts gb ON p.session_id = gb.session_id AND m.journee = gb.journee AND m.equipe_dom_id = gb.equipe_dom_id AND m.equipe_ext_id = gb.equipe_ext_id
                WHERE pmi.pari_multiple_id = %s
            """, (combo_id,))
            match_rows = cursor.fetchall()
            avg_conf = sum(row['fiabilite'] for row in match_rows) / len(match_rows) if match_rows else 0
            return {
                "id": combo_id,
                "journee": combo_row['journee'],
                "mise_ar": combo_row['mise_ar'],
                "cote_totale": combo_row['cote_totale'],
                "fiabilite": avg_conf,
                "predictions": [dict(row) for row in match_rows]
            }

    @app.get("/predictions/history")
    async def get_predictions_history(day: Optional[int] = Query(None)):
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT p.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
                       e2.nom as away, e2.logo_url as away_logo,
                       p.prediction, p.fiabilite, p.succes, m.status,
                       m.score_dom as score_home, m.score_ext as score_away,
                       m.cote_1, m.cote_x, m.cote_2, p.source,
                       gb.boost as ia_boost, gb.raison as ia_raison
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                LEFT JOIN groq_boosts gb ON p.session_id = gb.session_id AND m.journee = gb.journee AND m.equipe_dom_id = gb.equipe_dom_id AND m.equipe_ext_id = gb.equipe_ext_id
                WHERE p.session_id = %s AND p.succes IS NOT NULL
            """
            params = [session_id]
            if day:
                query += " AND m.journee = %s"
                params.append(day)
            query += " ORDER BY m.journee DESC, p.id DESC LIMIT 50"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    @app.get("/bets/history")
    async def get_bets_history():
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 'SIMPLE' as type, p.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
                       e2.nom as away, e2.logo_url as away_logo,
                       p.prediction, p.fiabilite, p.succes, m.status,
                       m.score_dom as score_home, m.score_ext as score_away,
                       p.source, hp.mise_ar, hp.cote_jouee as cote, hp.profit_net,
                       p.id as sort_key,
                       gb.boost as ia_boost, gb.raison as ia_raison
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                LEFT JOIN historique_paris hp ON p.id = hp.prediction_id
                LEFT JOIN groq_boosts gb ON p.session_id = gb.session_id AND m.journee = gb.journee AND m.equipe_dom_id = gb.equipe_dom_id AND m.equipe_ext_id = gb.equipe_ext_id
                WHERE p.session_id = %s AND p.succes IS NOT NULL
                AND p.id NOT IN (SELECT prediction_id FROM pari_multiple_items)
            """, (session_id,))
            simples = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT 'COMBO' as type, id, journee, mise_ar, cote_totale, resultat, profit_net, id as sort_key
                FROM pari_multiple
                WHERE session_id = %s AND resultat IS NOT NULL
            """, (session_id,))
            combos = [dict(row) for row in cursor.fetchall()]

            for c in combos:
                cursor.execute("""
                    SELECT p.id, m.journee, e1.nom as home, e2.nom as away, 
                           p.prediction, p.fiabilite, p.source, p.succes,
                           gb.boost as ia_boost, gb.raison as ia_raison
                    FROM pari_multiple_items pmi
                    JOIN predictions p ON pmi.prediction_id = p.id
                    JOIN matches m ON p.match_id = m.id
                    JOIN equipes e1 ON m.equipe_dom_id = e1.id
                    JOIN equipes e2 ON m.equipe_ext_id = e2.id
                    LEFT JOIN groq_boosts gb ON p.session_id = gb.session_id AND m.journee = gb.journee AND m.equipe_dom_id = gb.equipe_dom_id AND m.equipe_ext_id = gb.equipe_ext_id
                    WHERE pmi.pari_multiple_id = %s
                """, (c['id'],))
                c['matches'] = [dict(row) for row in cursor.fetchall()]

            history = simples + combos
            history.sort(key=lambda x: x.get('sort_key', 0), reverse=True)
            return history

    @app.get("/matches/next")
    async def get_next_match():
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
                       e2.nom as away, e2.logo_url as away_logo,
                       m.status, m.cote_1, m.cote_x, m.cote_2
                FROM matches m
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE m.session_id = %s AND m.status = 'A_VENIR'
                ORDER BY m.journee ASC, m.id ASC LIMIT 1
            """, (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    @app.get("/standings")
    async def get_standings():
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT e.nom as team, e.logo_url, c.points, c.forme as form, c.position, 
                       (c.journee) as played, c.buts_pour as goals_for, c.buts_contre as goals_against, c.journee
                FROM classement c
                JOIN equipes e ON c.equipe_id = e.id
                WHERE c.session_id = %s AND c.journee = (SELECT MAX(journee) FROM classement WHERE session_id = %s)
                ORDER BY c.points DESC, (c.buts_pour - c.buts_contre) DESC
            """, (session_id, session_id))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    @app.post("/admin/reset-data")
    async def reset_database_api(request: ResetRequest):
        if request.confirmation != "RESET":
            raise HTTPException(status_code=400, detail="Confirmation invalide. RESET requis.")
        try:
            with get_db_connection(write=True) as conn:
                cursor = conn.cursor()
                tables = ['pari_multiple_items', 'pari_multiple', 'historique_paris', 'groq_boosts', 'predictions', 'classement', 'matches', 'sessions', 'prisma_config']
                deleted = {}
                for t in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {t}")
                    deleted[t] = cursor.fetchone()['count']
                    cursor.execute(f"DELETE FROM {t}")
                cursor.execute("INSERT INTO prisma_config (key, value_int) VALUES ('bankroll', 20000) ON CONFLICT (key) DO UPDATE SET value_int = 20000")
                cursor.execute("SELECT COUNT(*) FROM equipes")
                equipes_count = cursor.fetchone()['count']
                conn.commit()
                return {"success": True, "deleted_counts": deleted, "preserved_teams": equipes_count}
        except Exception as e:
            logger.error(f"Reset error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/admin/override-stop-loss")
    async def override_stop_loss_api(request: OverrideRequest):
        try:
            with get_db_connection(write=True) as conn:
                from src.zeus.database.queries import set_stop_loss_override
                set_stop_loss_override(request.session_id, request.override, conn)
                return {"status": "success", "override": request.override}
        except Exception as e:
            logger.error(f"Override error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

def start_api_server(host: str = "127.0.0.1", port: int = 8000):
    app = create_app()
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": host, "port": port, "log_level": "info"},
        daemon=True,
        name="api-server"
    )
    server_thread.start()
    return server_thread
