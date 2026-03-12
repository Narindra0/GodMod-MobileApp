import os

# URLs de base (extraites du README)
URL_RESULTATS = "https://bet261.mg/virtual/category/instant-league/8035/results"
URL_MATCHS = "https://bet261.mg/virtual/category/instant-league/8035/matches"
URL_CLASSEMENT = "https://bet261.mg/virtual/category/instant-league/8035/ranking"

# Dossiers et Chemins
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "models")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Configuration de la base de données
DB_NAME = os.path.join(DATA_DIR, "godmod_database.db")

# Chemins des modèles ZEUS
ZEUS_MODEL_PATH = os.path.join(MODELS_DIR, "zeus", "best", "best_model.zip")
ZEUS_LOGS_DIR = os.path.join(LOGS_DIR, "zeus")

# Équipes de la English Virtual League (20)
EQUIPES = [
    "London Reds", "Manchester Blue", "Manchester Red", "Wolverhampton", "N. Forest",
    "Fulham", "West Ham", "Spurs", "London Blues", "Brighton",
    "Brentford", "Everton", "Aston Villa", "Leeds", "Sunderland",
    "Crystal Palace", "Liverpool", "Newcastle", "Burnley", "Bournemouth"
]

# Alias pour normaliser les noms d'équipes (Site -> DB)
TEAM_ALIASES = {
    "A. Villa": "Aston Villa",
    "C. Palace": "Crystal Palace",
    "Man Blue": "Manchester Blue",
    "Man Red": "Manchester Red",
}

# Paramètres de prédiction
JOURNEE_DEPART_PREDICTION = 2
MAX_PREDICTIONS_PAR_JOURNEE = 3

# Système de points PRISMA (Attribution lors de la validation des prédictions)
# Utilisé pour le calcul du score global de l'IA dans la table 'sessions'
PRISMA_POINTS_VICTOIRE = 5  # Points alloués pour une prédiction correcte
PRISMA_POINTS_DEFAITE = -8 # Points retirés pour une prédiction incorrecte

# ============================================
# CONFIGURATION DU SYSTÈME INTELLIGENT
# ============================================

# Mode d'intelligence activé par défaut au démarrage
USE_INTELLIGENCE_AMELIOREE = True

# Sélection améliorée (Phase 3 complète)
USE_SELECTION_AMELIOREE = True

# État de ZEUS pendant l'entraînement automatique
# Si True, ZEUS n'émet pas de prédictions pour éviter les conflits
ZEUS_DEEP_SLEEP = False
