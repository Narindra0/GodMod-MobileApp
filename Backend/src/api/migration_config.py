"""
Configuration de migration API v2.1
Systeme de bascule progressive Scraper -> API

Version: 2.1 - Phases 5 & 6
Date: Janvier 2025
"""

# ==================== CONFIGURATION DE MIGRATION ====================

# Active/Desactive l'utilisation de l'API pour chaque composant
# True = Utilise API, False = Utilise Scraper HTML
API_MIGRATION = {
    # Phase 5.1 - Classement
    "USE_API_RANKING": True,      # Basculer en premier (donnees les plus stables)
    
    # Phase 5.2 - Resultats
    "USE_API_RESULTS": True,      # Basculer ensuite
    
    # Phase 5.3 - Matchs a venir
    "USE_API_MATCHES": True,      # Basculer en dernier (cotes critiques)
    
    # Mode global
    "API_ONLY_MODE": True,        # True = API uniquement, False = Systeme hybride
}

# ==================== CONFIGURATION DE SECURITE ====================

# Monitoring et alertes
MONITORING = {
    "LOG_API_ERRORS": True,           # Logger toutes les erreurs API
    "ALERT_ON_403": True,             # Alerte si App-Version obsolete
    "FALLBACK_TO_SCRAPER": False,     # Rollback auto vers scraper si API fail
    "MAX_API_RETRIES": 3,             # Nombre de tentatives avant echec
}

# ==================== OPTIMISATIONS (Phase 6) ====================

# Cache pour reduire les appels API
CACHE_CONFIG = {
    "ENABLED": False,                 # Activer le cache (optionnel)
    "RANKING_CACHE_SECONDS": 3600,   # Cache classement 1h
    "RESULTS_CACHE_SECONDS": 1800,   # Cache resultats 30min
    "MATCHES_CACHE_SECONDS": 300,    # Cache matchs 5min
}

# Performance
PERFORMANCE = {
    "BATCH_INSERT": True,             # Insertion par lot en BDD
    "USE_CONNECTION_POOL": False,     # Pool de connexions (optionnel)
    "ASYNC_API_CALLS": False,         # Appels API asynchrones (optionnel)
}

# ==================== LEGACY SCRAPER (Phase 6) ====================

# Configuration du scraper HTML (desactive mais conserve)
LEGACY_SCRAPER = {
    "ENABLED": False,                 # Desactive par defaut
    "KEEP_CODE": True,                # Conserver le code (ne pas supprimer)
    "LOG_ACTIVITY": False,            # Logger l'activite du scraper
}

# ==================== HELPERS ====================

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


# ==================== PLAN DE MIGRATION ====================

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

# ==================== TEST ====================

if __name__ == "__main__":
    print("[CONFIG] Migration API v2.1")
    print("=" * 60)
    
    status = get_migration_status()
    print("\n[STATUT ACTUEL]")
    print(f"  Classement: {status['ranking'].upper()}")
    print(f"  Resultats: {status['results'].upper()}")
    print(f"  Matchs: {status['matches'].upper()}")
    print(f"  Mode API pur: {status['api_only_mode']}")
    print(f"  Legacy scraper: {'ACTIF' if status['legacy_enabled'] else 'DESACTIVE'}")
    
    print("\n" + "=" * 60)
    print(MIGRATION_PLAN)
