import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from src.core import config
from src.core.database import get_db_connection
from src.core.session_manager import get_active_session

from .models import AiSettingsUpdate, BorrowRequest, ForceTrainingRequest, OverrideRequest, PrismaSettingsUpdate, ResetRequest, AuditTriggerRequest

logger = logging.getLogger("server")

# Clé secrète admin (définir ADMIN_SECRET_KEY dans .env pour activer la protection)
ADMIN_HEADER_NAME = "X-Admin-Key"


def _get_admin_secret() -> str:
    return os.getenv("ADMIN_SECRET_KEY", "").strip()


def require_admin_access(
    request: Request,
    x_admin_key: Optional[str] = Header(None, alias=ADMIN_HEADER_NAME),
) -> None:
    admin_secret = _get_admin_secret()
    client_ip = request.client.host if request.client else "unknown"
    route = request.url.path

    if not admin_secret:
        logger.error("Protected write route unavailable: ADMIN_SECRET_KEY missing", extra={"route": route})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_SECRET_KEY is not configured. Protected write routes are disabled.",
        )

    if not x_admin_key or x_admin_key != admin_secret:
        logger.warning("Admin access denied", extra={"route": route, "client_ip": client_ip})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing or invalid {ADMIN_HEADER_NAME} header.",
        )

# =============================================================================
# REQUETES SQL CENTRALISEES
# =============================================================================
# Toutes les requêtes SQL sont définies ici pour faciliter la maintenance

# --- Requêtes Config ---
SQL_GET_AI_ENABLED = "SELECT value_int FROM prisma_config WHERE key = 'ai_enabled'"
SQL_GET_ENSEMBLE_ENABLED = "SELECT value_int FROM prisma_config WHERE key = 'ensemble_enabled'"
SQL_SET_AI_ENABLED = """
    INSERT INTO prisma_config (key, value_int) VALUES ('ai_enabled', %s)
    ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int
"""
SQL_SET_ENSEMBLE_ENABLED = """
    INSERT INTO prisma_config (key, value_int) VALUES ('ensemble_enabled', %s)
    ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int
"""

# --- Requêtes Audit ---
SQL_GET_LATEST_AUDIT = """
    SELECT start_journee, end_journee, report_json, timestamp 
    FROM ai_cycle_audits 
    ORDER BY id DESC LIMIT 1
"""

# --- Requêtes Sessions / Bankroll ---
SQL_GET_ZEUS_LAST_BANKROLL = """
    SELECT bankroll_apres FROM historique_paris 
    WHERE session_id = %s AND strategie = 'ZEUS' 
    ORDER BY id_pari DESC LIMIT 1
"""
SQL_UPDATE_ZEUS_DEBT = """
    UPDATE sessions
    SET dette_zeus = dette_zeus + %s,
        total_emprunte_zeus = total_emprunte_zeus + %s
    WHERE id = %s
"""
SQL_INSERT_ZEUS_BORROW = """
    INSERT INTO historique_paris (
        session_id, prediction_id, journee, type_pari, 
        mise_ar, profit_net, bankroll_apres, strategie, action_id
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
SQL_GET_SESSION_METRICS = """
    SELECT score_prisma, score_zeus, dette_zeus, total_emprunte_zeus, stop_loss_override 
    FROM sessions WHERE id = %s
"""

# --- Requêtes Predictions ---
SQL_COUNT_PREDICTIONS_TOTAL = """
    SELECT COUNT(*) FROM predictions WHERE session_id = %s AND succes IS NOT NULL
"""
SQL_COUNT_PREDICTIONS_WINS = """
    SELECT COUNT(*) FROM predictions WHERE session_id = %s AND succes = 1
"""
SQL_GET_ACTIVE_PREDICTIONS = """
    SELECT 'SIMPLE' as type, p.id, m.journee, e1.nom as home, e1.logo_url as home_logo, 
           e2.nom as away, e2.logo_url as away_logo, 
           p.prediction, p.fiabilite, p.succes, m.status,
           m.cote_1, m.cote_x, m.cote_2, p.source, p.technical_details,
           p.ai_analysis, p.ai_advice
    FROM predictions p
    JOIN matches m ON p.match_id = m.id
    JOIN equipes e1 ON m.equipe_dom_id = e1.id
    JOIN equipes e2 ON m.equipe_ext_id = e2.id
    WHERE p.session_id = %s AND p.succes IS NULL
    AND p.id NOT IN (
        SELECT pmi.prediction_id 
        FROM pari_multiple_items pmi
        JOIN pari_multiple pm ON pmi.pari_multiple_id = pm.id
        WHERE pm.session_id = %s AND pm.resultat IS NULL
    )
    ORDER BY m.journee DESC
"""
SQL_GET_PREDICTIONS_HISTORY = """
    SELECT 'SIMPLE' as type, p.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
           e2.nom as away, e2.logo_url as away_logo,
           p.prediction, p.fiabilite, p.succes, m.status,
           m.score_dom as score_home, m.score_ext as score_away,
           m.cote_1, m.cote_x, m.cote_2, p.source, p.technical_details,
           p.ai_analysis, p.ai_advice
    FROM predictions p
    JOIN matches m ON p.match_id = m.id
    JOIN equipes e1 ON m.equipe_dom_id = e1.id
    JOIN equipes e2 ON m.equipe_ext_id = e2.id
    WHERE p.session_id = %s AND p.succes IS NOT NULL
    {day_filter}
    ORDER BY m.journee DESC, p.id DESC LIMIT 50
"""

# --- Requêtes Paris Combinés ---
SQL_GET_COMBO_PREDICTIONS = """
    SELECT id, journee, mise_ar, cote_totale
    FROM pari_multiple
    WHERE session_id = %s AND resultat IS NULL
    ORDER BY id DESC LIMIT 1
"""
SQL_GET_COMBO_ITEMS = """
    SELECT p.id, m.journee, e1.nom as home, e2.nom as away, 
           p.prediction, p.fiabilite, p.source,
           CASE 
               WHEN p.prediction = '1' THEN m.cote_1
               WHEN p.prediction IN ('X', 'N') THEN m.cote_x
               WHEN p.prediction = '2' THEN m.cote_2
               WHEN p.prediction = '1X' THEN m.cote_1x
               WHEN p.prediction = '12' THEN m.cote_12
               WHEN p.prediction = 'X2' THEN m.cote_x2
           END as cote,
           p.technical_details, p.ai_analysis, p.ai_advice
    FROM pari_multiple_items pmi
    JOIN predictions p ON pmi.prediction_id = p.id
    JOIN matches m ON p.match_id = m.id
    JOIN equipes e1 ON m.equipe_dom_id = e1.id
    JOIN equipes e2 ON m.equipe_ext_id = e2.id
    WHERE pmi.pari_multiple_id = %s
"""
SQL_GET_COMBO_HISTORY = """
    SELECT 'COMBO' as type, id, journee, mise_ar, cote_totale, resultat, profit_net, id as sort_key
    FROM pari_multiple
    WHERE session_id = %s AND resultat IS NOT NULL
"""

# --- Requêtes Paris Simples ---
SQL_GET_BETS_SIMPLE_HISTORY = """
    SELECT 'SIMPLE' as type, p.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
           e2.nom as away, e2.logo_url as away_logo,
           p.prediction, p.fiabilite, p.succes, m.status,
           m.score_dom as score_home, m.score_ext as score_away,
           p.source, p.technical_details, hp.mise_ar, hp.cote_jouee as cote, hp.profit_net,
           p.id as sort_key, p.ai_analysis, p.ai_advice
    FROM predictions p
    JOIN matches m ON p.match_id = m.id
    JOIN equipes e1 ON m.equipe_dom_id = e1.id
    JOIN equipes e2 ON m.equipe_ext_id = e2.id
    LEFT JOIN historique_paris hp ON p.id = hp.prediction_id
    WHERE p.session_id = %s AND p.succes IS NOT NULL
    AND p.id NOT IN (SELECT prediction_id FROM pari_multiple_items)
"""

# --- Requêtes Matches ---
SQL_GET_NEXT_MATCH = """
    SELECT m.id, m.journee, e1.nom as home, e1.logo_url as home_logo,
           e2.nom as away, e2.logo_url as away_logo,
           m.status, m.cote_1, m.cote_x, m.cote_2
    FROM matches m
    JOIN equipes e1 ON m.equipe_dom_id = e1.id
    JOIN equipes e2 ON m.equipe_ext_id = e2.id
    WHERE m.session_id = %s AND m.status = 'A_VENIR'
    ORDER BY m.journee ASC, m.id ASC LIMIT 1
"""

# --- Requêtes Classement ---
SQL_GET_STANDINGS = """
    SELECT e.nom as team, e.logo_url, c.points, c.forme as form, c.position, 
           c.journee as played, c.buts_pour as goals_for, c.buts_contre as goals_against
    FROM classement c
    JOIN equipes e ON c.equipe_id = e.id
    WHERE c.session_id = %s AND c.journee = (SELECT MAX(journee) FROM classement WHERE session_id = %s)
    ORDER BY c.points DESC, (c.buts_pour - c.buts_contre) DESC
"""


def execute_prediction_query(cursor, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """
    Fonction utilitaire pour executer des requetes de prediction avec la structure de jointure commune
    Evite la duplication du code SQL complexe
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def parse_ai_analysis(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extrait et décode proprement l'analyse IA depuis technical_details ou ia_raison.
    Gère les formats JSON string et les objets déjà mappés en dict.
    """
    import json
    
    # 1. Lecture directe depuis col `ai_analysis` (nouveau format V5)
    if row.get('ai_analysis') or row.get('ai_advice'):
        return {
            "analysis": row.get('ai_analysis', ''),
            "advice": row.get('ai_advice', ''),
            "confidence": row.get('fiabilite', 0)
        }
        
    # 2. Priorité aux technical_details (format PRISMA v2)
    tech_details = row.get('technical_details')
    if tech_details:
        try:
            # Si c'est une chaîne JSON, on la décode
            if isinstance(tech_details, str):
                tech_details = json.loads(tech_details)
            
            # Si on a un dictionnaire, on cherche ai_analysis dedans
            if isinstance(tech_details, dict):
                ai = tech_details.get('ai_analysis')
                if ai:
                    return ai
        except:
            pass
            
    # 3. Fallback sur ia_raison (format legacy ou Zeus via groq_boosts)
    ia_raison = row.get('ia_raison')
    if ia_raison:
        try:
            # Si c'est une chaîne JSON, on la décode
            if isinstance(ia_raison, str):
                return json.loads(ia_raison)
            # Si c'est déjà un dictionnaire
            if isinstance(ia_raison, dict):
                return ia_raison
        except:
            # Si ce n'est pas du JSON, on retourne un objet minimal avec le texte brut
            if isinstance(ia_raison, str) and ia_raison.strip():
                return {
                    "analysis": ia_raison,
                    "confidence": row.get('fiabilite', 0),
                    "advice": "Analyse textuelle brute."
                }
                
    return None


def get_prisma_bankroll():
    """Read PRISMA bankroll from database via prisma_finance"""
    try:
        from src.core.prisma_finance import get_prisma_bankroll as get_bankroll_from_core

        return get_bankroll_from_core()
    except Exception as e:
        logger.error(f"Error reading PRISMA bankroll: {e}")
        return config.DEFAULT_BANKROLL

def get_zeus_bankroll():
    """Read ZEUS bankroll from database via zeus_finance"""
    try:
        from src.core.zeus_finance import get_zeus_bankroll as get_zeus_from_core

        return get_zeus_from_core()
    except Exception as e:
        logger.error(f"Error reading ZEUS bankroll: {e}")
        return config.DEFAULT_BANKROLL


def register_routes(app: FastAPI) -> None:
    @app.get("/health")
    async def health():
        try:
            active_session = get_active_session()
            return {"status": "ok", "session_id": active_session["id"]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/audits/latest")
    async def get_latest_audit():
        try:
            import json
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_GET_LATEST_AUDIT)
                    row = cur.fetchone()
                    if not row:
                        return {"audit": None}
                    
                    # Décodage du JSON stocké
                    report = row["report_json"]
                    if isinstance(report, str):
                        report = json.loads(report)
                        
                    return {
                        "start_journee": row["start_journee"],
                        "end_journee": row["end_journee"],
                        "report": report,
                        "timestamp": row["timestamp"]
                    }
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de l'audit : {e}")
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.post("/admin/audit/trigger")
    async def trigger_cycle_audit(
        request: AuditTriggerRequest,
        _: None = Depends(require_admin_access),
    ):
        try:
            from src.analysis.ai_booster import perform_cycle_audit_async
            active_session = get_active_session()
            session_id = active_session["id"]
            
            # Utiliser la journée fournie ou reculer à la dernière journée active
            journee = request.journee if request.journee else active_session.get("current_day", 10)
            
            # Lancement asynchrone explicite
            logger.info(f"[API] Déclenchement manuel de l'audit IA pour J{journee}")
            perform_cycle_audit_async(journee, session_id)
            
            return {
                "status": "success", 
                "message": f"Audit de la journée {journee} lancé en arrière-plan.",
                "session_id": session_id
            }
        except Exception as e:
            logger.error(f"Erreur déclenchement audit: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/admin/training/force")
    async def force_training(
        request: ForceTrainingRequest,
        _: None = Depends(require_admin_access),
    ):
        """Force l'entraînement PRISMA immédiatement"""
        try:
            from src.prisma.orchestrator import PrismaIntelligenceOrchestrator
            from src.prisma.training_status import status_manager
            from src.core.database import get_db_connection
            import threading

            # Mettre à jour le status IMMÉDIATEMENT pour que le dashboard réagisse
            status_manager.update_global(
                is_training=True,
                description="Démarrage entraînement forcé (manuel)..."
            )
            status_manager.add_log("🚀 Entraînement forcé démarré via API")
            logger.info("[TRAINING-FORCE] Status mis à jour: is_training=True")

            def run_training():
                try:
                    logger.info("[TRAINING-FORCE] Thread démarré")
                    with get_db_connection(write=True) as conn:
                        logger.info("[TRAINING-FORCE] Connexion DB OK")
                        orchestrator = PrismaIntelligenceOrchestrator(conn, force_training=request.force)
                        steps = request.steps if request.steps else ['train', 'validate', 'feedback']
                        logger.info(f"[TRAINING-FORCE] Lancement pipeline avec steps: {steps}")
                        results = orchestrator.run_full_pipeline(steps=steps)
                        logger.info(f"[TRAINING-FORCE] Pipeline terminé: {results}")
                        return results
                except Exception as e:
                    logger.error(f"[TRAINING-FORCE] Erreur dans le thread: {e}", exc_info=True)
                    status_manager.update_global(
                        is_training=False,
                        description=f"Erreur: {str(e)[:50]}"
                    )
                    status_manager.add_log(f"❌ Erreur: {str(e)}")
                    raise

            # Lancer en arrière-plan pour ne pas bloquer la réponse HTTP
            thread = threading.Thread(target=run_training, daemon=True)
            thread.start()
            logger.info(f"[TRAINING-FORCE] Thread lancé (ID: {thread.ident})")

            return {
                "status": "success",
                "message": f"Entraînement forcé lancé (steps: {request.steps or ['train', 'validate', 'feedback']})",
                "monitor_url": "/prisma/dashboard",
                "thread_id": thread.ident
            }
        except Exception as e:
            logger.error(f"Erreur lancement entraînement forcé: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/settings/ai")
    async def get_ai_settings():
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_GET_AI_ENABLED)
                    row = cur.fetchone()
                    ai_enabled = bool(row["value_int"]) if row and row["value_int"] is not None else True
                    return {"enabled": ai_enabled}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.post("/settings/ai")
    async def toggle_ai_settings(
        settings: AiSettingsUpdate,
        _: None = Depends(require_admin_access),
    ):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    val = 1 if settings.enabled else 0
                    cur.execute(SQL_SET_AI_ENABLED, (val,))
                    # Le context manager commit automatiquement
                    return {"status": "success", "enabled": settings.enabled}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.get("/settings/prisma-ml")
    async def get_prisma_ml_settings():
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(SQL_GET_ENSEMBLE_ENABLED)
                    row = cur.fetchone()
                    # Par défaut activé si non configuré
                    ensemble_enabled = bool(row["value_int"]) if row and row["value_int"] is not None else True
                    return {"ensemble_enabled": ensemble_enabled}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.post("/settings/prisma-ml")
    async def update_prisma_ml_settings(
        settings: PrismaSettingsUpdate,
        _: None = Depends(require_admin_access),
    ):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    val = 1 if settings.ensemble_enabled else 0
                    cur.execute(SQL_SET_ENSEMBLE_ENABLED, (val,))
                    # Le context manager commit automatiquement
                    return {"status": "success", "ensemble_enabled": settings.ensemble_enabled}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")

    @app.post("/zeus/borrow")
    async def zeus_borrow(
        request: BorrowRequest,
        _: None = Depends(require_admin_access),
    ):
        try:
            active_session = get_active_session()
            session_id = active_session["id"]
            with get_db_connection(write=True) as conn:
                cursor = conn.cursor()
                cursor.execute(SQL_UPDATE_ZEUS_DEBT, (request.amount, request.amount, session_id))

                cursor.execute(SQL_GET_ZEUS_LAST_BANKROLL, (session_id,))
                row = cursor.fetchone()
                current_bankroll = row["bankroll_apres"] if row else active_session["capital_initial"]
                new_bankroll = current_bankroll + request.amount

                cursor.execute(
                    SQL_INSERT_ZEUS_BORROW,
                    (session_id, None, 0, "EMPRUNT", 0, request.amount, new_bankroll, "ZEUS", 0),
                )

                # Mettre à jour le bankroll global ZEUS dans prisma_config
                from src.core.zeus_finance import update_zeus_bankroll
                update_zeus_bankroll(new_bankroll, conn=conn)

                # Le context manager commit automatiquement
                return {"status": "success", "new_bankroll": new_bankroll, "debt": request.amount}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur emprunt: {str(e)}")

    @app.get("/metrics/overview")
    async def get_metrics_overview():
        try:
            active_session = get_active_session()
            session_id = active_session["id"]
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(SQL_COUNT_PREDICTIONS_TOTAL, (session_id,))
                total = cursor.fetchone()["count"]
                cursor.execute(SQL_COUNT_PREDICTIONS_WINS, (session_id,))
                wins = cursor.fetchone()["count"]
                win_rate = (wins / total * 100) if total > 0 else 0

                bankroll_zeus = get_zeus_bankroll()

                bankroll_prisma = get_prisma_bankroll()

                profit_zeus = bankroll_zeus - active_session["capital_initial"]
                profit_prisma = bankroll_prisma - active_session["capital_initial"]
                total_profit = profit_zeus + profit_prisma

                cursor.execute(SQL_GET_SESSION_METRICS, (session_id,))
                session_data = cursor.fetchone()
                score_prisma = session_data["score_prisma"] if session_data else 0
                score_zeus = session_data["score_zeus"] if session_data else 0
                dette_zeus = session_data["dette_zeus"] if session_data else 0
                total_emprunte = session_data["total_emprunte_zeus"] if session_data else 0
                override = session_data["stop_loss_override"] if session_data else False

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
                    "stop_loss_override": override,
                }
        except Exception as e:
            logger.error(f"Error fetching metrics: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/predictions/active")
    async def get_active_predictions():
        active_session = get_active_session()
        session_id = active_session["id"]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            results = execute_prediction_query(cursor, SQL_GET_ACTIVE_PREDICTIONS, (session_id, session_id))
            for r in results:
                r['ai_analysis'] = parse_ai_analysis(r)
            return results

    @app.get("/predictions/combo")
    async def get_combo_predictions():
        active_session = get_active_session()
        session_id = active_session["id"]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(SQL_GET_COMBO_PREDICTIONS, (session_id,))
            combo_row = cursor.fetchone()
            if not combo_row:
                return {}

            combo_id = combo_row["id"]
            cursor.execute(SQL_GET_COMBO_ITEMS, (combo_id,))
            match_rows = cursor.fetchall()
            predictions_list = []
            for row in match_rows:
                r = dict(row)
                r['ai_analysis'] = parse_ai_analysis(r)
                predictions_list.append(r)

            avg_conf = sum(row["fiabilite"] for row in match_rows) / len(match_rows) if match_rows else 0
            return {
                "id": combo_id,
                "journee": combo_row["journee"],
                "mise_ar": combo_row["mise_ar"],
                "cote_totale": combo_row["cote_totale"],
                "fiabilite": avg_conf,
                "predictions": predictions_list,
            }

    @app.get("/predictions/history")
    async def get_predictions_history(day: Optional[int] = Query(None)):
        active_session = get_active_session()
        session_id = active_session["id"]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = SQL_GET_PREDICTIONS_HISTORY.format(day_filter=" AND m.journee = %s" if day else "")
            params = [session_id]
            if day:
                params.append(day)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = [dict(row) for row in rows]
            for r in results:
                r['ai_analysis'] = parse_ai_analysis(r)
            return results

    @app.get("/bets/history")
    async def get_bets_history():
        active_session = get_active_session()
        session_id = active_session["id"]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(SQL_GET_BETS_SIMPLE_HISTORY, (session_id,))
            simples = [dict(row) for row in cursor.fetchall()]

            cursor.execute(SQL_GET_COMBO_HISTORY, (session_id,))
            combos = [dict(row) for row in cursor.fetchall()]

            for c in combos:
                cursor.execute(SQL_GET_COMBO_ITEMS, (c["id"],))
                m_rows = cursor.fetchall()
                c_matches = []
                for m_row in m_rows:
                    mr = dict(m_row)
                    mr['ai_analysis'] = parse_ai_analysis(mr)
                    c_matches.append(mr)
                c["matches"] = c_matches

            history = simples + combos
            for h in history:
                h['ai_analysis'] = parse_ai_analysis(h)
            
            history.sort(key=lambda x: x.get("sort_key", 0), reverse=True)
            return history

    @app.get("/matches/next")
    async def get_next_match():
        active_session = get_active_session()
        session_id = active_session["id"]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(SQL_GET_NEXT_MATCH, (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    @app.get("/standings")
    async def get_standings():
        active_session = get_active_session()
        session_id = active_session["id"]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(SQL_GET_STANDINGS, (session_id, session_id))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    @app.post("/admin/reset-data")
    async def reset_database_api(
        request: ResetRequest,
        _: None = Depends(require_admin_access),
    ):
        if request.confirmation != "RESET":
            raise HTTPException(status_code=400, detail="Confirmation invalide. RESET requis.")
        try:
            with get_db_connection(write=True) as conn:
                cursor = conn.cursor()
                tables = [
                    "pari_multiple_items",
                    "pari_multiple",
                    "historique_paris",
                    "match_insights",
                    "predictions",
                    "classement",
                    "matches",
                    "ai_cycle_audits",
                    "sessions",
                    "prisma_config",
                ]
                deleted = {}
                for t in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {t}")
                    deleted[t] = cursor.fetchone()["count"]
                    cursor.execute(f"DELETE FROM {t}")
                # Initialisation des capitaux par défaut pour les deux stratégies
                for strat_key in ['bankroll_prisma', 'bankroll_zeus']:
                    cursor.execute(
                        "INSERT INTO prisma_config (key, value_int) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int",
                        (strat_key, config.DEFAULT_BANKROLL),
                    )
                # Réinitialiser les configs par défaut
                cursor.execute(
                    "INSERT INTO prisma_config (key, value_int) VALUES ('ai_enabled', 1) "
                    "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int"
                )
                cursor.execute(
                    "INSERT INTO prisma_config (key, value_int) VALUES ('ensemble_enabled', 1) "
                    "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int"
                )
                cursor.execute("SELECT COUNT(*) FROM equipes")
                equipes_count = cursor.fetchone()["count"]
                # Le context manager commit automatiquement
            # Fix #1 : Invalider le cache de session après le reset
            # Sans ça, PRISMA continuerait à utiliser l'ancien session_id supprimé
            from src.analysis.intelligence import vider_cache_intelligence
            vider_cache_intelligence()
            logger.info("[RESET] Cache intelligence invalidé après reset.")
            return {"success": True, "deleted_counts": deleted, "preserved_teams": equipes_count}
        except Exception as e:
            logger.error(f"Reset error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/admin/override-stop-loss")
    async def override_stop_loss_api(
        request: OverrideRequest,
        _: None = Depends(require_admin_access),
    ):
        try:
            with get_db_connection(write=True) as conn:
                from src.zeus.database.queries import set_stop_loss_override
                set_stop_loss_override(request.session_id, request.override, conn)
                return {"status": "success", "override": request.override}
        except Exception as e:
            logger.error(f"Override error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/prisma/training-status")
    async def get_training_status():
        try:
            # Récupérer l'état sans charger de gros modèle (immédiat)
            from src.prisma.training_status import status_manager
            return status_manager.get_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur status: {str(e)}")

    @app.get("/prisma/dashboard")
    async def get_prisma_dashboard():
        from fastapi.responses import HTMLResponse
        import os
        
        # Chemin absolu vers le ficher html d'interface dans le dossier tools
        html_path = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "prisma_dashboard.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            return HTMLResponse(content=html_content)
        except Exception as e:
            return HTMLResponse(content=f"<h1>Erreur : Fichier Dashboard introuvable</h1><p>{e}</p>", status_code=404)
