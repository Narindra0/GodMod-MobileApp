import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "models")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
# DB_NAME est obsolète, PostgreSQL est utilisé via les variables d'environnement dans .env
DB_NAME = None
ZEUS_MODEL_PATH = os.path.join(MODELS_DIR, "zeus", "best", "best_model.zip")
ZEUS_LOGS_DIR = os.path.join(LOGS_DIR, "zeus")
EQUIPES = [
    "London Reds", "Manchester Blue", "Manchester Red", "Wolverhampton", "N. Forest",
    "Fulham", "West Ham", "Spurs", "London Blues", "Brighton",
    "Brentford", "Everton", "Aston Villa", "Leeds", "Sunderland",
    "Crystal Palace", "Liverpool", "Newcastle", "Burnley", "Bournemouth"
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
VERBOSE_MODE = False

USE_INTELLIGENCE_AMELIOREE = True
USE_SELECTION_AMELIOREE = True
ZEUS_DEEP_SLEEP = False
ACTIVATE_MULTIPLE_BETS = True
MAX_COMBINED_MATCHES = 3
PERCENTAGE_BANKROLL_MULTIPLE = 0.05 
MONTANT_FIXE_MULTIPLE = 1000  
USE_MONTANT_FIXE = True  
BANKROLL_STOP_LOSS = 5000  # Ar — seuil de sécurité : tout pari est suspendu en dessous

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
    "West Ham": "https://i.ibb.co/c0ndsF5/West-Ham.png"
}

# --- Intégration IA Google Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# --- Intégration IA Groq (Fallback) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# --- Intégration IA DeepSeek (Officielle) ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")  # Options: deepseek-chat, deepseek-reasoner
