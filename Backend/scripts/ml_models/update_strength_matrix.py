#!/usr/bin/env python3
"""
Script de mise à jour de la matrice de force relative des équipes
À exécuter après chaque journée pour maintenir la matrice à jour
"""
import sys
import os

# Ajouter le répertoire parent au path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.db.database import get_db_connection
from src.core.system.session_manager import get_active_session
from src.prisma.team_strength_matrix import update_strength_matrix, get_matrix_stats, load_matrix
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_last_completed_journee():
    """Met à jour la matrice pour la dernière journée complétée."""
    try:
        with get_db_connection() as conn:
            # Récupérer la session active
            session = get_active_session(conn)
            if not session:
                logger.error("Aucune session active trouvée")
                return False
            
            session_id = session['id']
            
            # Trouver la dernière journée avec des résultats
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX(journee) as last_journee
                FROM matches 
                WHERE session_id = %s 
                AND score_dom IS NOT NULL 
                AND score_ext IS NOT NULL
            """, (session_id,))
            
            result = cursor.fetchone()
            if not result or not result['last_journee']:
                logger.info("Aucune journée complétée trouvée")
                return False
            
            last_journee = result['last_journee']
            logger.info(f"Mise à jour matrice pour Session {session_id}, Journée {last_journee}")
            
            # Charger la matrice existante
            load_matrix()
            
            # Mettre à jour avec les résultats de la journée
            update_strength_matrix(conn, session_id, last_journee)
            
            # Afficher les statistiques
            stats = get_matrix_stats()
            logger.info(f"Stats matrice: {stats['total_pairs']} paires, "
                       f"force moyenne: {stats['avg_strength']:.3f}, "
                       f"min: {stats['min_strength']:.3f}, "
                       f"max: {stats['max_strength']:.3f}")
            
            return True
            
    except Exception as e:
        logger.error(f"Erreur mise à jour matrice: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = update_last_completed_journee()
    if success:
        print("✅ Matrice de force mise à jour avec succès")
    else:
        print("❌ Échec mise à jour matrice")
        sys.exit(1)
