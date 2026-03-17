import os
import threading
import uvicorn
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from src.core.database import get_db_connection
from src.core.session_manager import get_active_session
from src.core import config
from src.core.init_data import initialize_all
import json

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
    return app

def get_prisma_bankroll():
    """Read PRISMA bankroll from JSON file"""
    try:
        from src.core.prisma_finance import get_prisma_bankroll as get_bankroll_from_core
        return get_bankroll_from_core()
    except ImportError:
        # Fallback si le module n'est pas disponible
        prisma_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'Prisma.json')
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(prisma_path), exist_ok=True)
        
        # Create file with default bankroll if it doesn't exist
        if not os.path.exists(prisma_path):
            default_data = {"bankroll": 20000}
            with open(prisma_path, 'w') as f:
                json.dump(default_data, f)
            return default_data["bankroll"]
        
        # Read existing file
        with open(prisma_path, 'r') as f:
            data = json.load(f)
            return data.get('bankroll', 20000)  # Default to 20000 if not found
    except Exception as e:
        print(f"Error reading PRISMA bankroll: {e}")
        return 20000  # Fallback value

def register_routes(app: FastAPI):
    @app.get("/health")
    async def health():
        try:
            active_session = get_active_session()
            return {"status": "ok", "session_id": active_session['id']}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/metrics/overview")
    async def get_metrics_overview():
        active_session = get_active_session()
        session_id = active_session['id']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Wins & Win Rate
            cursor.execute("SELECT COUNT(*) FROM predictions WHERE session_id = ? AND succes IS NOT NULL", (session_id,))
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM predictions WHERE session_id = ? AND succes = 1", (session_id,))
            wins = cursor.fetchone()[0]
            win_rate = (wins / total * 100) if total > 0 else 0

            # Bankrolls & Profit
            cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = ? ORDER BY id_pari DESC LIMIT 1", (session_id,))
            row = cursor.fetchone()
            current_bankroll = row[0] if row else active_session['capital_initial']
            profit = current_bankroll - active_session['capital_initial']

            # Scores (Prisma & Zeus)
            cursor.execute("SELECT score_prisma, score_zeus FROM sessions WHERE id = ?", (session_id,))
            scores = cursor.fetchone()
            score_prisma = scores[0] if scores else 0
            score_zeus = scores[1] if scores else 0

            return {
                "win_rate": round(win_rate, 1),
                "total_predictions": total,
                "wins": wins,
                "bankroll": current_bankroll,
                "profit": profit,
                "score_ia": score_prisma + score_zeus,
                "bankroll_zeus": current_bankroll,
                "bankroll_prisma": get_prisma_bankroll()  # Use PRISMA bankroll from JSON
            }

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
                       m.cote_1, m.cote_x, m.cote_2, p.source
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE p.session_id = ? AND p.succes IS NULL
                AND p.id NOT IN (
                    SELECT pmi.prediction_id 
                    FROM pari_multiple_items pmi
                    JOIN pari_multiple pm ON pmi.pari_multiple_id = pm.id
                    WHERE pm.session_id = ? AND pm.resultat IS NULL
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
            # Get the latest active combo
            cursor.execute("""
                SELECT id, journee, mise_ar, cote_totale
                FROM pari_multiple
                WHERE session_id = ? AND resultat IS NULL
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            combo_row = cursor.fetchone()
            if not combo_row:
                return {}

            combo_id = combo_row['id']
            # Get matches for this combo
            cursor.execute("""
                SELECT p.id, m.journee, e1.nom as home, e2.nom as away, 
                       p.prediction, p.fiabilite, p.source,
                       CASE 
                           WHEN p.prediction = '1' THEN m.cote_1
                           WHEN p.prediction = 'X' THEN m.cote_x
                           WHEN p.prediction = '2' THEN m.cote_2
                       END as cote
                FROM pari_multiple_items pmi
                JOIN predictions p ON pmi.prediction_id = p.id
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE pmi.pari_multiple_id = ?
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
                       m.cote_1, m.cote_x, m.cote_2, p.source
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE p.session_id = ? AND p.succes IS NOT NULL
            """
            params = [session_id]
            if day:
                query += " AND m.journee = ?"
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
            
            # 1. Fetch Simple Predictions (that were NOT part of a combo)
            cursor.execute("""
                SELECT 'SIMPLE' as type, p.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
                       e2.nom as away, e2.logo_url as away_logo,
                       p.prediction, p.fiabilite, p.succes, m.status,
                       p.source, p.id as sort_key
                FROM predictions p
                JOIN matches m ON p.match_id = m.id
                JOIN equipes e1 ON m.equipe_dom_id = e1.id
                JOIN equipes e2 ON m.equipe_ext_id = e2.id
                WHERE p.session_id = ? AND p.succes IS NOT NULL
                AND p.id NOT IN (SELECT prediction_id FROM pari_multiple_items)
            """, (session_id,))
            simples = [dict(row) for row in cursor.fetchall()]

            # 2. Fetch Combo Bets (validated)
            cursor.execute("""
                SELECT 'COMBO' as type, id, journee, mise_ar, cote_totale, resultat, profit_net, id as sort_key
                FROM pari_multiple
                WHERE session_id = ? AND resultat IS NOT NULL
            """, (session_id,))
            combos = [dict(row) for row in cursor.fetchall()]

            for c in combos:
                cursor.execute("""
                    SELECT p.id, m.journee, e1.nom as home, e2.nom as away, 
                           p.prediction, p.fiabilite, p.source, p.succes
                    FROM pari_multiple_items pmi
                    JOIN predictions p ON pmi.prediction_id = p.id
                    JOIN matches m ON p.match_id = m.id
                    JOIN equipes e1 ON m.equipe_dom_id = e1.id
                    JOIN equipes e2 ON m.equipe_ext_id = e2.id
                    WHERE pmi.pari_multiple_id = ?
                """, (c['id'],))
                c['matches'] = [dict(row) for row in cursor.fetchall()]

            # 3. Combine and Sort
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
                WHERE m.session_id = ? AND m.status = 'A_VENIR'
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
                WHERE c.session_id = ? AND c.journee = (SELECT MAX(journee) FROM classement WHERE session_id = ?)
                ORDER BY c.points DESC, (c.buts_pour - c.buts_contre) DESC
            """, (session_id, session_id))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
def start_api_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    app = create_app()
    register_routes(app)
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
