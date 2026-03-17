import sqlite3
import os
import sys

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import config
from src.core.database import get_db_connection

def populate_logos():
    print("Démarrage de la population des logos...")
    
    with get_db_connection(write=True) as conn:
        cursor = conn.cursor()
        
        updated_count = 0
        for team_name, logo_url in config.TEAM_LOGOS.items():
            cursor.execute("UPDATE equipes SET logo_url = ? WHERE nom = ?", (logo_url, team_name))
            if cursor.rowcount > 0:
                print(f"[SUCCESS] Logo mis à jour pour : {team_name}")
                updated_count += 1
            else:
                # Try with alias if not found
                # Note: config.TEAM_LOGOS uses the canonical names from config.EQUIPES
                print(f"[WARNING] Équipe non trouvée dans la BDD : {team_name}")
        
        print(f"\nTerminé ! {updated_count} logos mis à jour.")

if __name__ == "__main__":
    populate_logos()
