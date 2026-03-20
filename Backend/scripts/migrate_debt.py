import sys
import os
from dotenv import load_dotenv

# Ajouter le chemin du projet pour les imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.database import get_db_connection

def migrate():
    print("🚀 Démarrage de la migration de la base de données...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier si les colonnes existent déjà
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='sessions' AND column_name='dette_zeus'
            """)
            if not cursor.fetchone():
                print("➕ Ajout de la colonne 'dette_zeus'...")
                cursor.execute("ALTER TABLE sessions ADD COLUMN dette_zeus INTEGER DEFAULT 0")
            else:
                print("✅ Colonne 'dette_zeus' déjà présente.")

            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='sessions' AND column_name='total_emprunte_zeus'
            """)
            if not cursor.fetchone():
                print("➕ Ajout de la colonne 'total_emprunte_zeus'...")
                cursor.execute("ALTER TABLE sessions ADD COLUMN total_emprunte_zeus INTEGER DEFAULT 0")
            else:
                print("✅ Colonne 'total_emprunte_zeus' déjà présente.")
                
            conn.commit()
            print("✨ Migration terminée avec succès!")
    except Exception as e:
        print(f"❌ Erreur lors de la migration: {e}")

if __name__ == "__main__":
    migrate()
