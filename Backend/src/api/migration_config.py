"""
Configuration de migration API v2.1
Systeme de bascule progressive Scraper -> API

Version: 2.1 - Phases 5 & 6
Date: Janvier 2025
"""

API_MIGRATION = {
    "USE_API_RANKING": True,
    "USE_API_RESULTS": True,
    "USE_API_MATCHES": True,
    "API_ONLY_MODE": True,
}

MONITORING = {
    "LOG_API_ERRORS": True,
    "ALERT_ON_403": True,
    "FALLBACK_TO_SCRAPER": False,
    "MAX_API_RETRIES": 3,
}

CACHE_CONFIG = {
    "ENABLED": False,
    "RANKING_CACHE_SECONDS": 3600,
    "RESULTS_CACHE_SECONDS": 1800,
    "MATCHES_CACHE_SECONDS": 300,
}

PERFORMANCE = {
    "BATCH_INSERT": True,
    "USE_CONNECTION_POOL": False,
    "ASYNC_API_CALLS": False,
}

LEGACY_SCRAPER = {
    "ENABLED": False,
    "KEEP_CODE": True,
    "LOG_ACTIVITY": False,
}

def is_api_enabled(component: str) -> bool:
    """
    Verifie si l'API est activee pour un composant specifique
    
    Args:
        component: "ranking", "results", ou "matches"
        
    Returns:
        True si API activee pour ce composant
    """
    mapping = {
        "ranking": "USE_API_RANKING",
        "results": "USE_API_RESULTS",
        "matches": "USE_API_MATCHES"
    }
    
    key = mapping.get(component)
    if key:
        return API_MIGRATION.get(key, False)
    
    return False


def get_data_source(component: str) -> str:
    """
    Retourne la source de donnees active pour un composant
    
    Args:
        component: "ranking", "results", ou "matches"
        
    Returns:
        "api" ou "scraper"
    """
    return "api" if is_api_enabled(component) else "scraper"


def get_migration_status() -> dict:
    """
    Retourne le statut complet de la migration
    
    Returns:
        Dictionnaire avec le statut de chaque composant
    """
    return {
        "ranking": get_data_source("ranking"),
        "results": get_data_source("results"),
        "matches": get_data_source("matches"),
        "api_only_mode": API_MIGRATION["API_ONLY_MODE"],
        "legacy_enabled": LEGACY_SCRAPER["ENABLED"]
    }


MIGRATION_PLAN = """
PLAN DE MIGRATION API v2.1
==========================

Phase 5.1 - Classement (Journee 1)
-----------------------------------
1. Definir: USE_API_RANKING = True
2. Redemarrer le systeme
3. Surveiller logs pendant 24-48h
4. Valider coherence des donnees

Phase 5.2 - Resultats (Journee 3)
----------------------------------
1. Definir: USE_API_RESULTS = True
2. Redemarrer le systeme
3. Surveiller logs pendant 24-48h
4. Valider coherence des scores

Phase 5.3 - Matchs (Journee 5)
-------------------------------
1. Definir: USE_API_MATCHES = True
2. Redemarrer le systeme
3. Surveiller logs pendant 24-48h
4. Valider coherence des cotes

Phase 6 - Finalisation (Journee 7)
-----------------------------------
1. Definir: API_ONLY_MODE = True
2. Definir: LEGACY_SCRAPER["ENABLED"] = False
3. Nettoyer imports inutilises
4. Optimiser performances

ROLLBACK (si probleme)
----------------------
Remettre les flags a False et redemarrer
"""
