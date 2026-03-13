import time
from . import config

_EQUIPE_ID_CACHE = {}

def get_equipe_id(nom, conn=None):
    """Récupère l'ID d'une équipe par son nom, utilise le cache."""
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
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM equipes WHERE nom = ?", (nom,))
        res = cursor.fetchone()
        
        if res:
            _EQUIPE_ID_CACHE[nom] = res[0]
            return res[0]
        return None


def _update_config_flag(flag_name, new_value):
    """
    Fonction générique pour mettre à jour un flag dans config.py.
    """
    import os
    
    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith(flag_name):
                lines[i] = f"{flag_name} = {new_value}\n"
                updated = True
                break
        
        if not updated:
            for i, line in enumerate(lines):
                if line.strip().startswith("# Sélecteurs CSS"):
                    lines.insert(i, f"{flag_name} = {new_value}\n")
                    updated = True
                    break
        
        if updated:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
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
    """
    return _update_config_flag("USE_INTELLIGENCE_AMELIOREE", new_value)

def update_selection_flag(new_value):
    """
    Met à jour le flag USE_SELECTION_AMELIOREE dans config.py (Phase 3).
    """
    return _update_config_flag("USE_SELECTION_AMELIOREE", new_value)

def update_global_intelligence_flags(new_value):
    """
    Met à jour simultanément les flags USE_INTELLIGENCE_AMELIOREE et USE_SELECTION_AMELIOREE dans config.py.
    """
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
        
        if updated_count > 0:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
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
        