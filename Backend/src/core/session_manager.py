import sqlite3
import logging
from datetime import datetime
from . import config
from .database import get_db_connection
logger = logging.getLogger(__name__)
SESSION_MAX_DAYS = 37
def get_active_session(conn=None):
    if conn:
        return _get_active_session_internal(conn)
    with get_db_connection() as conn:
        return _get_active_session_internal(conn)
def _get_active_session_internal(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT id, current_day, capital_initial FROM sessions WHERE status = 'ACTIVE' LIMIT 1")
    row = cursor.fetchone()
    if row:
        return {
            'id': row[0],
            'current_day': row[1],
            'capital_initial': row[2]
        }
    else:
        return create_new_session(conn=conn)
def create_new_session(previous_capital=None, conn=None):
    if conn:
        return _create_new_session_internal(conn, previous_capital)
    with get_db_connection(write=True) as conn:
        return _create_new_session_internal(conn, previous_capital)
def _create_new_session_internal(conn, previous_capital=None):
    cursor = conn.cursor()
    cursor.execute("SELECT id, capital_initial, score_prisma FROM sessions WHERE status = 'ACTIVE' LIMIT 1")
    active = cursor.fetchone()
    capital_to_use = previous_capital or 20000
    prisma_to_use = 200
    if active:
        active_id = active[0]
        prisma_to_use = active[2]
        cursor.execute("SELECT bankroll_apres FROM historique_paris WHERE session_id = ? ORDER BY id_pari DESC LIMIT 1", (active_id,))
        last_bankroll = cursor.fetchone()
        capital_final = last_bankroll[0] if last_bankroll else active[1]
        capital_to_use = capital_final
        cursor.execute("""
            UPDATE sessions 
            SET status = 'CLOSED', 
                timestamp_fin = CURRENT_TIMESTAMP,
                capital_final = ?
            WHERE id = ?
        """, (capital_final, active_id))
        logger.info(f"Session {active_id} fermée (Capital: {capital_final}, Score PRISMA: {prisma_to_use})")
    cursor.execute("""
        INSERT INTO sessions (timestamp_debut, status, current_day, capital_initial, type_session, score_zeus, score_prisma)
        VALUES (CURRENT_TIMESTAMP, 'ACTIVE', 1, ?, 'PRODUCTION', 0, ?)
    """, (capital_to_use, prisma_to_use))
    new_id = cursor.lastrowid
    logger.info(f"Nouvelle session {new_id} créée (Jour 1, Capital: {capital_to_use}, Score PRISMA: {prisma_to_use})")
    return {
        'id': new_id,
        'current_day': 1,
        'capital_initial': capital_to_use,
        'score_prisma': prisma_to_use
    }
def update_session_day(session_id, day_number, conn=None):
    if day_number > SESSION_MAX_DAYS:
        logger.info(f"Jour {day_number} atteint (Limite: {SESSION_MAX_DAYS}). Transition vers nouvelle session.")
        return create_new_session(conn=conn)
    if conn:
        return _update_session_day_internal(conn, session_id, day_number)
    with get_db_connection(write=True) as conn:
        return _update_session_day_internal(conn, session_id, day_number)
def _update_session_day_internal(conn, session_id, day_number):
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET current_day = ? WHERE id = ?", (day_number, session_id))
    logger.info(f"Session {session_id} mise à jour au jour {day_number}")
    return {
        'id': session_id,
        'current_day': day_number
    }
