import psycopg2
import os
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

def migrate():
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST"),
        port=os.getenv("PG_PORT"),
        database=os.getenv("PG_DATABASE"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD")
    )
    
    try:
        cursor = conn.cursor()
        print("Modification de la table historique_paris...")
        
        # Supprimer la contrainte NOT NULL
        cursor.execute("ALTER TABLE historique_paris ALTER COLUMN prediction_id DROP NOT NULL;")
        
        conn.commit()
        print("Migration réussie : prediction_id est maintenant NULLABLE.")
        
    except Exception as e:
        print(f"Erreur lors de la migration : {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
