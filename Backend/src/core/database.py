import psycopg2
import psycopg2.extras
import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Configuration PostgreSQL
PG_HOST = os.getenv('PG_HOST', 'localhost')
PG_PORT = os.getenv('PG_PORT', '5432')
PG_DATABASE = os.getenv('PG_DATABASE', 'godmod_db')
PG_USER = os.getenv('PG_USER', 'postgres')
PG_PASSWORD = os.getenv('PG_PASSWORD', 'CONFIRMER')

# Équipes
EQUIPES = [
    "London Reds", "Manchester Blue", "Manchester Red", "Wolverhampton", "N. Forest",
    "Fulham", "West Ham", "Spurs", "London Blues", "Brighton",
    "Brentford", "Everton", "Aston Villa", "Leeds", "Sunderland",
    "Crystal Palace", "Liverpool", "Newcastle", "Burnley", "Bournemouth"
]

@contextmanager
def get_db_connection(write: bool = False):
    """
    Context manager pour les connexions PostgreSQL
    """
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur DB PostgreSQL, rollback effectué: {e}", exc_info=True)
        raise
    finally:
        conn.close()

def create_new_schema(conn):
    """
    Crée le schéma PostgreSQL
    """
    cursor = conn.cursor()
    
    # Table equipes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS equipes (
        id SERIAL PRIMARY KEY,
        nom VARCHAR(255) UNIQUE NOT NULL,
        logo_url TEXT
    );
    """)
    
    # Table sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        timestamp_debut TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        timestamp_fin TIMESTAMP,
        status VARCHAR(20) DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'CLOSED')),
        current_day INTEGER DEFAULT 1,
        capital_initial INTEGER DEFAULT 20000,
        capital_final INTEGER,
        profit_total INTEGER,
        version_ia TEXT,
        type_session VARCHAR(20) DEFAULT 'PRODUCTION' CHECK(type_session IN ('TRAINING', 'EVALUATION', 'PRODUCTION')),
        score_zeus INTEGER DEFAULT 0,
        score_prisma INTEGER DEFAULT 200,
        dette_zeus INTEGER DEFAULT 0,
        total_emprunte_zeus INTEGER DEFAULT 0,
        stop_loss_override BOOLEAN DEFAULT FALSE
    );
    """)
    
    # Table matches
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        equipe_dom_id INTEGER NOT NULL,
        equipe_ext_id INTEGER NOT NULL,
        cote_1 DECIMAL(5,2),
        cote_x DECIMAL(5,2),
        cote_2 DECIMAL(5,2),
        score_dom INTEGER,
        score_ext INTEGER,
        status VARCHAR(20) CHECK(status IN ('A_VENIR', 'TERMINE')),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
        FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id),
        UNIQUE(session_id, journee, equipe_dom_id, equipe_ext_id)
    );
    """)
    
    # Table classement
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classement (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        equipe_id INTEGER NOT NULL,
        position INTEGER,
        points INTEGER NOT NULL,
        forme TEXT,
        buts_pour DECIMAL(4,2) DEFAULT 0,
        buts_contre DECIMAL(4,2) DEFAULT 0,
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (equipe_id) REFERENCES equipes(id),
        UNIQUE(session_id, journee, equipe_id)
    );
    """)
    
    # Table predictions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        prediction VARCHAR(10) NOT NULL,
        resultat VARCHAR(10),
        fiabilite DECIMAL(5,2),
        succes INTEGER,
        source VARCHAR(20) DEFAULT 'PRISMA',
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (match_id) REFERENCES matches(id)
    );
    """)
    
    # Table historique_paris
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historique_paris (
        id_pari SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        prediction_id INTEGER,
        journee INTEGER,
        type_pari VARCHAR(50),
        mise_ar INTEGER,
        pourcentage_bankroll REAL,
        cote_jouee REAL,
        resultat INTEGER,
        profit_net INTEGER,
        bankroll_apres INTEGER NOT NULL,
        timestamp_pari TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        action_id INTEGER,
        strategie VARCHAR(20) DEFAULT 'ZEUS',
        probabilite_implicite REAL,
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
    );
    """)
    
    # Table pari_multiple
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pari_multiple (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        mise_ar INTEGER NOT NULL,
        cote_totale REAL NOT NULL,
        bankroll_apres INTEGER,
        resultat INTEGER,
        profit_net INTEGER,
        timestamp_pari TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """)
    
    # Table pari_multiple_items
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pari_multiple_items (
        id SERIAL PRIMARY KEY,
        pari_multiple_id INTEGER NOT NULL,
        prediction_id INTEGER NOT NULL,
        FOREIGN KEY (pari_multiple_id) REFERENCES pari_multiple(id),
        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
    );
    """)
    
    # Table prisma_config (Nouveau)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS prisma_config (
        key VARCHAR(50) PRIMARY KEY,
        value_int INTEGER,
        value_float REAL,
        value_text TEXT,
        last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # Initialisation du bankroll PRISMA et des configs par défaut si absents
    cursor.execute("INSERT INTO prisma_config (key, value_int) VALUES ('bankroll', 20000) ON CONFLICT (key) DO NOTHING;")
    cursor.execute("INSERT INTO prisma_config (key, value_int) VALUES ('ai_enabled', 1) ON CONFLICT (key) DO NOTHING;")

    # Table groq_boosts (cache des analyses IA Groq par journée)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groq_boosts (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        equipe_dom_id INTEGER NOT NULL,
        equipe_ext_id INTEGER NOT NULL,
        boost REAL NOT NULL DEFAULT 0.0,
        raison TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, journee, equipe_dom_id, equipe_ext_id),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """)

    conn.commit()


def initialiser_db():
    """
    Initialise la base de données PostgreSQL
    """
    try:
        with get_db_connection() as conn:
            create_new_schema(conn)
            
            cursor = conn.cursor()
            
            # Insertion des équipes
            cursor.executemany(
                'INSERT INTO equipes (nom) VALUES (%s) ON CONFLICT (nom) DO NOTHING',
                [(e,) for e in EQUIPES]
            )
            
            logger.info("Création des index PostgreSQL...")
            
            # Index pour performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_matches_session ON matches(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_matches_journee ON matches(journee)",
                "CREATE INDEX IF NOT EXISTS idx_matches_status_journee ON matches(status, journee)",
                "CREATE INDEX IF NOT EXISTS idx_classement_session ON classement(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_classement_recherche ON classement(session_id, equipe_id, journee)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_session ON predictions(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_attente ON predictions(session_id, succes)",
                "CREATE INDEX IF NOT EXISTS idx_historique_session ON historique_paris(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)",
                "CREATE INDEX IF NOT EXISTS idx_matches_equipes ON matches(session_id, equipe_dom_id, equipe_ext_id)",
                "CREATE INDEX IF NOT EXISTS idx_groq_boosts_lookup ON groq_boosts(session_id, journee)"
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            conn.commit()
            logger.info(f"{len(indexes)} index créés avec succès.")
            print(f"Base de données PostgreSQL initialisée (Architecture par Sessions v4).")
            
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation PostgreSQL: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    initialiser_db()
