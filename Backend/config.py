"""
Configuration et constantes globales pour le Backend
Centralise les valeurs numériques pour éviter les "nombres magiques"
"""

# Limites et tailles de traitement
DEFAULT_MARGIN = 16
MAX_ITEMS = 50
MAX_PREDICTIONS = 900

# Configuration base de données
DEFAULT_BATCH_SIZE = 1000
DB_TIMEOUT = 30
MAX_CONNECTIONS = 20

# Configuration API
API_TIMEOUT = 30000
RATE_LIMIT_REQUESTS = 100
RATE_LIMIT_WINDOW = 3600

# Configuration IA et Machine Learning
MODEL_TIMEOUT = 300
TRAINING_EPOCHS = 100
BATCH_SIZE = 32

# Valeurs par défaut pour le système
DEFAULT_BANKROLL = 20000
MIN_PREDICTION_CONFIDENCE = 0.6
MAX_ODDS_VALUE = 10.0

# Logging et monitoring
LOG_LEVEL = "INFO"
LOG_RETENTION_DAYS = 30
METRICS_INTERVAL = 60
