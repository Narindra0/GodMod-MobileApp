import sqlite3
import os
import sys

# Assure que le dossier Backend/ est dans sys.path (portable)
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from src.core.database import get_db_connection

def test_api_queries():
    print("Testing API Queries logic...")
    session_id = 3 # From logs
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Test /predictions/active query logic
        print("- Testing /predictions/active query...")
        try:
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
            print(f"  Success! Found {len(rows)} active predictions.")
        except Exception as e:
            print(f"  FAILED: {e}")

        # Test prediction insertion logic (from intelligence.py)
        print("- Testing prediction insertion...")
        try:
            # We use a dummy insert to verify it works
            # Find a valid match_id
            cursor.execute("SELECT id FROM matches LIMIT 1")
            match_row = cursor.fetchone()
            if match_row:
                match_id = match_row[0]
                cursor.execute("INSERT INTO predictions (session_id, match_id, prediction, fiabilite, source) VALUES (?, ?, ?, ?, ?)",
                             (session_id, match_id, '1', 0.9, 'TEST_SOURCE'))
                print("  Success! Insertion with 'source' column worked.")
                # Rollback is automatically handled by get_db_connection if we raise or just wait, 
                # but here it might commit because we are in a with block. 
                # Let's delete it manually to be safe or just let it be since it's a test.
                conn.rollback() # We don't want to pollute DB
            else:
                print("  SKIPPED: No match found in DB to test insert.")
        except Exception as e:
            print(f"  FAILED: {e}")

if __name__ == "__main__":
    test_api_queries()
