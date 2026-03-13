"""
Utilitaires pour la gestion des équipes et leurs logos
"""

from .database import get_db_connection

def get_equipe_logo(equipe_id=None, equipe_nom=None):
    """
    Récupère l'URL du logo d'une équipe
    
    Args:
        equipe_id: ID de l'équipe (prioritaire)
        equipe_nom: Nom de l'équipe (si ID non fourni)
    
    Returns:
        str: URL du logo ou None si non trouvé
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if equipe_id:
                cursor.execute("SELECT logo_url FROM equipes WHERE id = ?", (equipe_id,))
            elif equipe_nom:
                cursor.execute("SELECT logo_url FROM equipes WHERE nom = ?", (equipe_nom,))
            else:
                return None
                
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
            
    except Exception as e:
        print(f"Erreur lors de la récupération du logo: {e}")
        return None

def get_toutes_les_equipes_avec_logos():
    """
    Récupère toutes les équipes avec leurs logos
    
    Returns:
        list: Liste de dictionnaires {id, nom, logo_url}
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, nom, logo_url FROM equipes ORDER BY nom")
            
            equipes = []
            for row in cursor.fetchall():
                equipes.append({
                    'id': row[0],
                    'nom': row[1],
                    'logo_url': row[2]
                })
            
            return equipes
            
    except Exception as e:
        print(f"Erreur lors de la récupération des équipes: {e}")
        return []

def get_equipes_par_ids(equipe_ids):
    """
    Récupère les informations de plusieurs équipes par leurs IDs
    
    Args:
        equipe_ids: Liste des IDs des équipes
    
    Returns:
        list: Liste de dictionnaires {id, nom, logo_url}
    """
    if not equipe_ids:
        return []
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Créer la clause IN avec le bon nombre de paramètres
            placeholders = ','.join(['?' for _ in equipe_ids])
            query = f"SELECT id, nom, logo_url FROM equipes WHERE id IN ({placeholders}) ORDER BY nom"
            
            cursor.execute(query, equipe_ids)
            
            equipes = []
            for row in cursor.fetchall():
                equipes.append({
                    'id': row[0],
                    'nom': row[1],
                    'logo_url': row[2]
                })
            
            return equipes
            
    except Exception as e:
        print(f"Erreur lors de la récupération des équipes: {e}")
        return []

def get_match_with_logos(match_id):
    """
    Récupère les informations d'un match avec les logos des deux équipes
    
    Args:
        match_id: ID du match
    
    Returns:
        dict: Dictionnaire avec les infos du match et logos
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            query = """
            SELECT m.id, m.journee, m.score_dom, m.score_ext, m.status,
                   e1.id as dom_id, e1.nom as dom_nom, e1.logo_url as dom_logo,
                   e2.id as ext_id, e2.nom as ext_nom, e2.logo_url as ext_logo
            FROM matches m
            JOIN equipes e1 ON m.equipe_dom_id = e1.id
            JOIN equipes e2 ON m.equipe_ext_id = e2.id
            WHERE m.id = ?
            """
            
            cursor.execute(query, (match_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'id': row[0],
                    'journee': row[1],
                    'score_dom': row[2],
                    'score_ext': row[3],
                    'status': row[4],
                    'equipe_dom': {
                        'id': row[5],
                        'nom': row[6],
                        'logo_url': row[7]
                    },
                    'equipe_ext': {
                        'id': row[8],
                        'nom': row[9],
                        'logo_url': row[10]
                    }
                }
            
            return None
            
    except Exception as e:
        print(f"Erreur lors de la récupération du match: {e}")
        return None
