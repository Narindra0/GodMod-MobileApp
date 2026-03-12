import time
from . import config

# Cache global pour les IDs d'équipes {nom: id}
_EQUIPE_ID_CACHE = {}

def get_equipe_id(nom, conn=None):
    """Récupère l'ID d'une équipe par son nom, utilise le cache."""
    global _EQUIPE_ID_CACHE
    if nom in _EQUIPE_ID_CACHE:
        return _EQUIPE_ID_CACHE[nom]
    
    if conn is None:
        from .database import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM equipes WHERE nom = ?", (nom,))
            res = cursor.fetchone()
            
            if res:
                _EQUIPE_ID_CACHE[nom] = res[0]
                return res[0]
            return None
    else:
        # Utilisation de la connexion fournie
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM equipes WHERE nom = ?", (nom,))
        res = cursor.fetchone()
        
        if res:
            _EQUIPE_ID_CACHE[nom] = res[0]
            return res[0]
        return None

def invalidate_equipe_cache():
    """Invalide le cache des équipes (utile après modifications)."""
    global _EQUIPE_ID_CACHE
    _EQUIPE_ID_CACHE.clear()

def _update_config_flag(flag_name, new_value):
    """
    Fonction générique pour mettre à jour un flag dans config.py.
    
    Args:
        flag_name: Nom du flag à mettre à jour (ex: "USE_INTELLIGENCE_AMELIOREE")
        new_value: Nouvelle valeur (True/False)
    
    Returns:
        True si la mise à jour a réussi, False sinon
    """
    import os
    
    # Chemin vers config.py
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    
    try:
        # Lire le fichier
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Trouver et remplacer la ligne
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith(flag_name):
                # Remplacer la ligne en conservant les commentaires si présents
                lines[i] = f"{flag_name} = {new_value}\n"
                updated = True
                break
        
        if not updated:
            # Si la ligne n'existe pas, l'ajouter avant les sélecteurs CSS
            for i, line in enumerate(lines):
                if line.strip().startswith("# Sélecteurs CSS"):
                    lines.insert(i, f"{flag_name} = {new_value}\n")
                    updated = True
                    break
        
        if updated:
            # Réécrire le fichier
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            # Recharger le module config pour que les changements soient pris en compte
            import importlib
            import sys
            if 'src.core.config' in sys.modules:
                importlib.reload(sys.modules['src.core.config'])
            
            return True
        else:
            return False
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Erreur lors de la mise à jour du flag {flag_name} : {e}", exc_info=True)
        return False

def update_intelligence_flag(new_value):
    """
    Met à jour le flag USE_INTELLIGENCE_AMELIOREE dans config.py.
    
    Args:
        new_value: True pour activer l'intelligence améliorée, False pour la désactiver
    
    Returns:
        True si la mise à jour a réussi, False sinon
    """
    return _update_config_flag("USE_INTELLIGENCE_AMELIOREE", new_value)

def update_selection_flag(new_value):
    """
    Met à jour le flag USE_SELECTION_AMELIOREE dans config.py (Phase 3).
    
    Args:
        new_value: True pour activer la sélection améliorée (Phase 3), False pour Phase 2
    
    Returns:
        True si la mise à jour a réussi, False sinon
    """
    return _update_config_flag("USE_SELECTION_AMELIOREE", new_value)

def update_global_intelligence_flags(new_value):
    """
    Met à jour simultanément les flags USE_INTELLIGENCE_AMELIOREE et USE_SELECTION_AMELIOREE dans config.py.
    
    Args:
        new_value: True pour activer tout le système d'intelligence, False pour le mode simple.
    
    Returns:
        True si la mise à jour a réussi, False sinon.
    """
    # On met à jour les deux flags séquentiellement
    # Note: On pourrait optimiser pour faire une seule écriture, mais _update_config_flag est déjà implémentée.
    # On va faire une implémentation optimisée locale pour éviter deux écritures fichiers.
    import os
    
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        updated_count = 0
        flags_to_update = ["USE_INTELLIGENCE_AMELIOREE", "USE_SELECTION_AMELIOREE"]
        
        for i, line in enumerate(lines):
            line_strip = line.strip()
            for flag in flags_to_update:
                if line_strip.startswith(flag):
                    lines[i] = f"{flag} = {new_value}\n"
                    updated_count += 1
        
        # Si on a trouvé au moins un flag, on réécrit
        if updated_count > 0:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            # Recharger le module config
            import importlib
            import sys
            if 'src.core.config' in sys.modules:
                importlib.reload(sys.modules['src.core.config'])
                
            return True
        return False
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Erreur lors de la mise à jour globale des flags : {e}", exc_info=True)
        return False