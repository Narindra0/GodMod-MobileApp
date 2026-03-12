import sqlite3
import logging
from contextlib import contextmanager
from . import config

# Configuration du logging
logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """
    Context manager pour les connexions DB.
    Gère automatiquement l'ouverture, la configuration, le commit/rollback et la fermeture.
    Améliore les performances avec WAL mode et assure la sécurité des transactions.
    """
    conn = sqlite3.connect(config.DB_NAME)
    conn.row_factory = sqlite3.Row  # Accès par nom de colonne
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Améliore les performances en lecture/écriture
    conn.execute("PRAGMA synchronous = NORMAL")  # Équilibre performance/sécurité
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur DB, rollback effectué: {e}", exc_info=True)
        raise
    finally:
        conn.close()

def create_new_schema(conn):
    """Définit le nouveau schéma de la base de données organisé par sessions (v4)."""
    cursor = conn.cursor()
    
    # 1. Table equipes (Référentiel global)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS equipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT UNIQUE NOT NULL
    );
    """)

    # 2. Table sessions (Le pivot de l'architecture)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_debut TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        timestamp_fin TIMESTAMP,
        status TEXT DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'CLOSED')),
        current_day INTEGER DEFAULT 1, -- Compteur de 1 à 37
        capital_initial INTEGER DEFAULT 20000,
        capital_final INTEGER,
        version_ia TEXT,
        type_session TEXT DEFAULT 'PRODUCTION' CHECK(type_session IN ('TRAINING', 'EVALUATION', 'PRODUCTION')),
        score_zeus INTEGER DEFAULT 0,
        score_prisma INTEGER DEFAULT 200
    );
    """)

    # 3. Table matches (Liée à une session)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL, -- Journée relative à la saison réelle (1-38)
        equipe_dom_id INTEGER NOT NULL,
        equipe_ext_id INTEGER NOT NULL,
        cote_1 DECIMAL(5,2),
        cote_x DECIMAL(5,2),
        cote_2 DECIMAL(5,2),
        score_dom INTEGER,
        score_ext INTEGER,
        status TEXT CHECK(status IN ('A_VENIR', 'TERMINE')),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
        FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id),
        UNIQUE(session_id, journee, equipe_dom_id, equipe_ext_id)
    );
    """)

    # 4. Table classement (Liée à une session)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # 5. Table predictions (Liée à une session)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        prediction TEXT NOT NULL,
        resultat TEXT,
        fiabilite DECIMAL(5,2),
        succes INTEGER,
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (match_id) REFERENCES matches(id)
    );
    """)

    # 6. Table historique_paris (Liée à une session)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historique_paris (
        id_pari INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        prediction_id INTEGER NOT NULL,
        journee INTEGER,
        type_pari TEXT,
        mise_ar INTEGER,
        pourcentage_bankroll REAL,
        cote_jouee REAL,
        resultat INTEGER,
        profit_net INTEGER,
        bankroll_apres INTEGER NOT NULL,
        timestamp_pari TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        action_id INTEGER,
        strategie TEXT DEFAULT 'ZEUS',
        probabilite_implicite REAL,
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
    );
    """)
    conn.commit()

def initialiser_db():
    """Initialise la base de données avec la nouvelle structure par sessions."""
    conn = sqlite3.connect(config.DB_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")

    # Création des tables
    create_new_schema(conn)

    # --- IMPORTANT : Initialisation des données de base ---
    
    # 1. Insérer les équipes si elles n'existent pas
    cursor.executemany('INSERT OR IGNORE INTO equipes (nom) VALUES (?)', [(e,) for e in config.EQUIPES])
    
    # 2. Création des index pour optimiser les performances
    logger.info("Création des index SQL...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_matches_session ON matches(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_matches_journee ON matches(journee)",
        "CREATE INDEX IF NOT EXISTS idx_classement_session ON classement(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_predictions_session ON predictions(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_historique_session ON historique_paris(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)"
    ]
    
    for index_sql in indexes:
        cursor.execute(index_sql)
    
    conn.commit()
    conn.close()
    logger.info(f"{len(indexes)} index crees avec succes.")
    print(f"Base de donnees '{config.DB_NAME}' initialisée (Architecture par Sessions v4).")
if __name__ == "__main__":
    initialiser_db()