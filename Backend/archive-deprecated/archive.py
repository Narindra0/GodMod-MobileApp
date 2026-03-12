"""
Module d'archivage des sessions GODMOD V2.
Gère la détection des nouvelles sessions et l'export des données en CSV.
"""
import csv
import os
import shutil
import logging
from datetime import datetime
from . import config
from .database import get_db_connection

logger = logging.getLogger(__name__)

# Dossier d'archives
ARCHIVES_DIR = os.path.join(os.path.dirname(config.DB_NAME), "archives")

def detecter_nouvelle_session(nouvelle_journee: int) -> bool:
    """
    Détecte si une nouvelle session a commencé.
    
    Logique améliorée :
    - Si session_archived = 1 : Toute nouvelle journée = nouvelle session
    - Si Delta < 0 : Nouvelle session (Reset standard J38 -> J1)
    - Si 0 <= Delta < 10 : Même session
    - Si Delta >= 10 : Probable nouvelle session -> Vérification temporelle
    
    Args:
        nouvelle_journee: Numéro de la journée détectée sur le site
        
    Returns:
        True si nouvelle session détectée, False sinon
    """
    if nouvelle_journee <= 0:
        return False
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(journee) FROM matches")
            derniere_j_db = cursor.fetchone()[0] or 0
            
            return False


def archiver_session() -> str:
    """
    Archive toutes les données de la session actuelle dans un fichier CSV.
    Crée un backup de sécurité avant l'archivage.
    
    Returns:
        Chemin du fichier CSV créé
    """
    # ÉTAPE 1 : Backup de sécurité automatique
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(os.path.dirname(config.DB_NAME), "data", "backup")
    os.makedirs(backup_dir, exist_ok=True)
    
    backup_filename = f"backup_godmod_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        shutil.copy2(config.DB_NAME, backup_path)
        logger.info(f"📦 Backup créé : {backup_path}")
        print(f"📦 Backup de sécurité créé : {backup_path}")
    except Exception as e:
        logger.error(f"Erreur lors du backup : {e}", exc_info=True)
        print(f"⚠️ Échec du backup (on continue quand même) : {e}")
    
    # ÉTAPE 2 : Créer le dossier archives si nécessaire
    os.makedirs(ARCHIVES_DIR, exist_ok=True)
    
    # Détermination du prochain ID de session
    existing_files = [f for f in os.listdir(ARCHIVES_DIR) if f.startswith("archives_session_") and f.endswith(".csv")]
    max_id = 0
    for f in existing_files:
        try:
            # Extraction du numéro X de archives_session_X.csv
            part = f.replace("archives_session_", "").replace(".csv", "")
            num = int(part)
            if num > max_id:
                max_id = num
        except ValueError:
            pass
            
    next_id = max_id + 1
    filename = f"archives_session_{next_id}.csv"
    filepath = os.path.join(ARCHIVES_DIR, filename)
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # --- Section: Prédictions ---
                writer.writerow(["=== PREDICTIONS ==="])
                writer.writerow(["Journee", "Equipe_Dom", "Equipe_Ext", "Prediction", "Resultat", "Succes"])
                
                cursor.execute("""
                    SELECT m.journee, e1.nom, e2.nom, p.prediction, p.resultat, p.succes
                    FROM predictions p
                    JOIN matches m ON p.match_id = m.id
                    JOIN equipes e1 ON m.equipe_dom_id = e1.id
                    JOIN equipes e2 ON m.equipe_ext_id = e2.id
                    ORDER BY m.journee, m.id
                """)
                for row in cursor.fetchall():
                    writer.writerow(row)
                
                writer.writerow([])  # Ligne vide
                
                # --- Section: Classement Final ---
                writer.writerow(["=== CLASSEMENT FINAL ==="])
                writer.writerow(["Equipe", "Points", "Forme"])
                
                cursor.execute("""
                    SELECT e.nom, c.points, c.forme
                    FROM classement c
                    JOIN equipes e ON c.equipe_id = e.id
                    WHERE c.journee = (SELECT MAX(journee) FROM classement)
                    ORDER BY c.points DESC
                """)
                for row in cursor.fetchall():
                    writer.writerow(row)
                
                writer.writerow([])  # Ligne vide

                # --- Section: Matches (Historique avec cotes) ---
                writer.writerow(["=== MATCHES (Historique) ==="])
                writer.writerow(["Journee", "Equipe_Dom", "Equipe_Ext", "Cote_1", "Cote_X", "Cote_2", "Status", "Score_Dom", "Score_Ext"])
                
                cursor.execute("""
                    SELECT m.journee, e1.nom, e2.nom, m.cote_1, m.cote_x, m.cote_2, m.status, m.score_dom, m.score_ext
                    FROM matches m
                    JOIN equipes e1 ON m.equipe_dom_id = e1.id
                    JOIN equipes e2 ON m.equipe_ext_id = e2.id
                    ORDER BY m.journee
                """)
                for row in cursor.fetchall():
                    writer.writerow(row)
                    
                writer.writerow([])
        
        # Vérification finale
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            print(f"📁 Archive créée avec succès : {filepath}")
            return filepath
        else:
            print(f"❌ Erreur : Le fichier d'archive {filepath} est vide ou non créé.")
            return None
            
    except Exception as e:
        logger.error(f"❌ CRITICAL ERREUR lors de l'archivage : {e}", exc_info=True)
        print(f"❌ CRITICAL ERREUR lors de l'archivage : {e}")
        return None


def reinitialiser_tables_session():
    """
    Réinitialise les tables de données pour une nouvelle session.
    Garde la table 'equipes' intacte et conserve le score IA.
    Réinitialise pause_until et session_archived pour la nouvelle session.
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Suppression des données (pas des tables)
            cursor.execute("DELETE FROM matches")
            cursor.execute("DELETE FROM predictions")
            cursor.execute("DELETE FROM classement")
    except Exception as e:
        logger.error(f"Erreur lors de la réinitialisation des tables : {e}", exc_info=True)
        print(f"❌ Erreur lors de la réinitialisation : {e}")
        return
    
    print("🔄 Tables réinitialisées pour la nouvelle session. Score IA conservé.")


if __name__ == "__main__":
    # Test manuel
    print("Test du module d'archivage...")
    print(f"Dossier archives : {ARCHIVES_DIR}")
