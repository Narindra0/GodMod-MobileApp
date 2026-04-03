import os
from typing import List
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "models")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
ZEUS_MODEL_PATH = os.path.join(MODELS_DIR, "zeus", "best", "best_model.zip")
ZEUS_LOGS_DIR = os.path.join(LOGS_DIR, "zeus")
DEFAULT_BANKROLL = 20000
DEFAULT_CORS_ORIGINS = [
    "http://localhost:19006",
    "http://localhost:8000",
    "http://127.0.0.1:19006",
    "http://127.0.0.1:8000",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
]
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))


def get_cors_origins() -> List[str]:
    env_val = os.getenv("CORS_ORIGINS")
    if env_val:
        return [o.strip() for o in env_val.split(",") if o.strip()]
    return list(DEFAULT_CORS_ORIGINS)


EQUIPES = [
    "London Reds",
    "Manchester Blue",
    "Manchester Red",
    "Wolverhampton",
    "N. Forest",
    "Fulham",
    "West Ham",
    "Spurs",
    "London Blues",
    "Brighton",
    "Brentford",
    "Everton",
    "Aston Villa",
    "Leeds",
    "Sunderland",
    "Crystal Palace",
    "Liverpool",
    "Newcastle",
    "Burnley",
    "Bournemouth",
]
TEAM_ALIASES = {
    "A. Villa": "Aston Villa",
    "C. Palace": "Crystal Palace",
    "Man Blue": "Manchester Blue",
    "Man Red": "Manchester Red",
}
JOURNEE_DEPART_PREDICTION = 2
MAX_PREDICTIONS_PAR_JOURNEE = 3
PRISMA_POINTS_VICTOIRE = 5
PRISMA_POINTS_DEFAITE = -8
SESSION_MAX_DAYS = 37  # Durée standard d'une session
VERBOSE_MODE = False

USE_INTELLIGENCE_AMELIOREE = True
USE_SELECTION_AMELIOREE = True
ACTIVATE_MULTIPLE_BETS = True
MAX_COMBINED_MATCHES = 3
PERCENTAGE_BANKROLL_MULTIPLE = 0.05
MONTANT_FIXE_MULTIPLE = 1000
USE_MONTANT_FIXE = True
BANKROLL_STOP_LOSS = 5000  # Ar — seuil de sécurité : tout pari est suspendu en dessous

# --- XGBoost / PRISMA v2 ---
PRISMA_XGBOOST_ENABLED = True   # Active le moteur hybride XGBoost + PRISMA classique
PRISMA_XGBOOST_WEIGHT = 0.6     # Poids XGBoost dans le blend (0.4 pour PRISMA classique)
PRISMA_XGBOOST_MIN_MATCHES = 100  # Nombre minimum de matchs pour entraîner le modèle
ENSEMBLE_XGBOOST_WEIGHT = 0.5      # Poids XGBoost dans l'ensemble (0.5 = égal avec CatBoost)

# --- Poisson / Validation Score ---
PRISMA_POISSON_ENABLED = True
PRISMA_POISSON_MIN_MATCHES = 10

# --- Kelly Criterion / Gestion de Mise ---
PRISMA_KELLY_ENABLED = True
PRISMA_KELLY_FRACTION = 0.2     # Multiplicateur de Kelly (0.2 = Quarter Kelly approx)
PRISMA_MAX_STAKE = 2000         # Plafond strict par pari en Ariary
PRISMA_MIN_STAKE = 1000         # Plancher strict par pari en Ariary


TEAM_LOGOS = {
    "Aston Villa": "https://i.ibb.co/nSL3kbr/A-Villa.png",
    "Bournemouth": "https://i.ibb.co/Xr4YSPXG/Bournemouth.png",
    "Brentford": "https://i.ibb.co/WpxwgCBY/Brentford.png",
    "Brighton": "https://i.ibb.co/1GryRKMZ/Brighton.png",
    "Burnley": "https://i.ibb.co/XxGDHzvs/Burnley.png",
    "Crystal Palace": "https://i.ibb.co/Wp2N1y1N/C-Palace.png",
    "Everton": "https://i.ibb.co/qMFDtqjc/Everton.png",
    "Fulham": "https://i.ibb.co/Y4qckfs6/Fulham.png",
    "Liverpool": "https://i.ibb.co/nsV4hSvf/Liverpool.png",
    "Leeds": "https://i.ibb.co/5Wxf4vkR/Leeds.png",
    "London Blues": "https://i.ibb.co/SwC4mfWf/London-Blues.png",
    "London Reds": "https://i.ibb.co/Mk1zxtxd/London-Reds.png",
    "Manchester Blue": "https://i.ibb.co/wF7MSBFp/Manchester-Blue.png",
    "Manchester Red": "https://i.ibb.co/V0vzTQsC/Manchester-Red.png",
    "Newcastle": "https://i.ibb.co/4RgpcZT9/Newcastle.png",
    "N. Forest": "https://i.ibb.co/zWSmsQfC/N-Forest.png",
    "Spurs": "https://i.ibb.co/DP9c3dt4/Spurs.png",
    "Sunderland": "https://i.ibb.co/yB036qRS/Sunderland.png",
    "Wolverhampton": "https://i.ibb.co/6VhKcC6/Wolverhampton.png",
    "West Ham": "https://i.ibb.co/c0ndsF5/West-Ham.png",
}

# --- Intégration IA Google Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# --- Intégration IA Groq (Fallback) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
