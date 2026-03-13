import time
import logging
from functools import wraps
from .database import get_db_connection

logger = logging.getLogger(__name__)

def retry_database_lock(max_retries=3, delay=0.5):
    """
    Décorateur pour réessayer les opérations de base de données en cas de "database is locked".
    
    Args:
        max_retries: Nombre maximum de tentatives (défaut: 3)
        delay: Délai entre les tentatives en secondes (défaut: 0.5)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if "database is locked" in str(e).lower() and attempt < max_retries:
                        logger.warning(f"Tentative {attempt + 1}/{max_retries + 1} échouée (DB locked). Nouvel essai dans {delay}s...")
                        time.sleep(delay * (attempt + 1))  # Délai croissant
                        continue
                    else:
                        break
            
            # Si on arrive ici, toutes les tentatives ont échoué
            logger.error(f"Échec après {max_retries + 1} tentatives: {last_exception}")
            raise last_exception
        
        return wrapper
    return decorator
