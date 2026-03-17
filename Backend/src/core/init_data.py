import os
import json
import sqlite3
from .database import get_db_connection
from . import config

def initialize_prisma_file():
    """Crée le fichier Prisma.json s'il n'existe pas"""
    prisma_path = os.path.join(config.DATA_DIR, "Prisma.json")
    
    # Crée le répertoire data s'il n'existe pas
    os.makedirs(config.DATA_DIR, exist_ok=True)
    
    if not os.path.exists(prisma_path):
        default_data = {"bankroll": 20000}
        with open(prisma_path, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, indent=2, ensure_ascii=False)
        print(f"Fichier Prisma.json créé avec bankroll par défaut: {default_data['bankroll']} Ar")
        return True
    return False

def initialize_team_logos():
    """Vérifie et peuple les logos des équipes s'ils sont manquants"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifie s'il y a des équipes sans logo
            cursor.execute("SELECT COUNT(*) FROM equipes WHERE logo_url IS NULL OR logo_url = ''")
            missing_logos_count = cursor.fetchone()[0]
            
            if missing_logos_count > 0:
                print(f"{missing_logos_count} équipe(s) sans logo trouvé(s), mise à jour en cours...")
                
                updated_count = 0
                for team_name, logo_url in config.TEAM_LOGOS.items():
                    cursor.execute("UPDATE equipes SET logo_url = ? WHERE nom = ? AND (logo_url IS NULL OR logo_url = '')", 
                                 (logo_url, team_name))
                    if cursor.rowcount > 0:
                        print(f"✓ Logo mis à jour pour : {team_name}")
                        updated_count += 1
                
                # Vérifie aussi avec les alias
                for alias, canonical_name in config.TEAM_ALIASES.items():
                    if canonical_name in config.TEAM_LOGOS:
                        logo_url = config.TEAM_LOGOS[canonical_name]
                        cursor.execute("UPDATE equipes SET logo_url = ? WHERE nom = ? AND (logo_url IS NULL OR logo_url = '')", 
                                     (logo_url, alias))
                        if cursor.rowcount > 0:
                            print(f"✓ Logo mis à jour pour alias : {alias}")
                            updated_count += 1
                
                conn.commit()
                print(f"Terminé ! {updated_count} logos mis à jour.")
                return True
            else:
                print("Toutes les équipes ont déjà des logos.")
                return False
                
    except Exception as e:
        print(f"Erreur lors de l'initialisation des logos: {e}")
        return False

def initialize_all():
    """Initialise toutes les données requises au démarrage"""
    print("🚀 Initialisation des données...")
    
    prisma_created = initialize_prisma_file()
    logos_updated = initialize_team_logos()
    
    if prisma_created or logos_updated:
        print("✅ Initialisation terminée avec succès!")
    else:
        print("ℹ️  Toutes les données sont déjà initialisées.")

if __name__ == "__main__":
    initialize_all()
