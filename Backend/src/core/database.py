import logging
import os
from contextlib import contextmanager
from urllib.parse import quote_plus

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from . import config

logger = logging.getLogger(__name__)

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(
            f"Variable d'environnement manquante: {name}. "
            "Veuillez la definir dans le fichier .env."
        )
    return value


# Configuration PostgreSQL
# On tente d'abord de récupérer l'URL complète (Neon, Render, etc.)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Fallback sur les paramètres individuels si DATABASE_URL n'est pas définie
    PG_HOST = _require_env("PG_HOST")
    PG_PORT = _require_env("PG_PORT")
    PG_DATABASE = _require_env("PG_DATABASE")
    PG_USER = _require_env("PG_USER")
    PG_PASSWORD = _require_env("PG_PASSWORD")
else:
    # On initialise à None pour éviter les erreurs de référence plus bas
    PG_HOST = PG_PORT = PG_DATABASE = PG_USER = PG_PASSWORD = None


@contextmanager
def get_db_connection(write: bool = False):
    """
    Context manager pour les connexions PostgreSQL.
    Tente d'abord une connexion DSN avec URL encoding (robuste pour les mots de passe spéciaux),
    puis une connexion par paramètres avec UTF8 explicite en fallback.
    """
    connection_attempts = []
    
    # Si on a une DATABASE_URL, c'est la priorité absolue (plus robuste)
    if DATABASE_URL:
        connection_attempts.append({
            'dsn': DATABASE_URL,
            'cursor_factory': psycopg2.extras.RealDictCursor
        })
    
    # Fallback ou complément avec les paramètres individuels
    if PG_USER and PG_PASSWORD and PG_HOST:
        connection_attempts.extend([
            {
                'dsn': f"postgresql://{quote_plus(PG_USER)}:{quote_plus(PG_PASSWORD)}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}",
                'cursor_factory': psycopg2.extras.RealDictCursor
            },
            {
                'host': PG_HOST,
                'port': PG_PORT,
                'database': PG_DATABASE,
                'user': PG_USER,
                'password': PG_PASSWORD,
                'cursor_factory': psycopg2.extras.RealDictCursor,
                'client_encoding': 'UTF8'
            }
        ])

    conn = None
    last_error = None

    for i, params in enumerate(connection_attempts):
        try:
            conn = psycopg2.connect(**params)
            break
        except Exception as e:
            last_error = e
            logger.warning(f"Échec connexion PostgreSQL tentative #{i+1}: {e}")
            continue

    if conn is None:
        logger.error(f"Impossible de se connecter à PostgreSQL: {last_error}")
        if isinstance(last_error, Exception):
            raise last_error
        raise RuntimeError("Impossible de se connecter à PostgreSQL")

    try:
        yield conn
        if conn is not None:
            conn.commit()
    except Exception as e:
        if conn is not None:
            conn.rollback()
        logger.error(f"Erreur DB PostgreSQL, rollback effectué: {e}", exc_info=True)
        raise
    finally:
        if conn is not None:
            conn.close()


def create_new_schema(conn):
    """
    Crée le schéma PostgreSQL
    """
    cursor = conn.cursor()

    # Table equipes
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS equipes (
        id SERIAL PRIMARY KEY,
        nom VARCHAR(255) UNIQUE NOT NULL,
        logo_url TEXT
    );
    """
    )

    # Table sessions
    cursor.execute(
        """
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
    """
    )

    # Table matches
    cursor.execute(
        """
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
    """
    )

    # Table classement
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS classement (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        equipe_id INTEGER NOT NULL,
        position INTEGER,
        points INTEGER NOT NULL,
        forme TEXT,
        buts_pour INTEGER DEFAULT 0,
        buts_contre INTEGER DEFAULT 0,
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (equipe_id) REFERENCES equipes(id),
        UNIQUE(session_id, journee, equipe_id)
    );
    """
    )

    # Table predictions
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        prediction VARCHAR(10) NOT NULL,
        resultat VARCHAR(10),
        fiabilite DECIMAL(5,2),
        succes INTEGER,
        source VARCHAR(20) DEFAULT 'PRISMA',
        technical_details JSONB,
        ai_analysis TEXT,
        ai_advice TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (match_id) REFERENCES matches(id),
        UNIQUE(session_id, match_id, source)
    );
    """
    )

    # Table historique_paris
    cursor.execute(
        """
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
    """
    )

    # Table pari_multiple
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS pari_multiple (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        mise_ar INTEGER NOT NULL,
        cote_totale REAL NOT NULL,
        bankroll_apres INTEGER,
        resultat INTEGER,
        profit_net INTEGER,
        strategie VARCHAR(20) DEFAULT 'PRISMA',
        timestamp_pari TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """
    )

    # Table pari_multiple_items
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS pari_multiple_items (
        id SERIAL PRIMARY KEY,
        pari_multiple_id INTEGER NOT NULL,
        prediction_id INTEGER NOT NULL,
        FOREIGN KEY (pari_multiple_id) REFERENCES pari_multiple(id),
        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
    );
    """
    )

    # Table prisma_config (Nouveau)
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS prisma_config (
        key VARCHAR(50) PRIMARY KEY,
        value_int INTEGER,
        value_float REAL,
        value_text TEXT,
        last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    )

    # Initialisation des bankrolls séparés et configs par défaut si absents
    cursor.execute(
        "INSERT INTO prisma_config (key, value_int) VALUES ('bankroll_prisma', 20000) ON CONFLICT (key) DO NOTHING;"
    )
    cursor.execute(
        "INSERT INTO prisma_config (key, value_int) VALUES ('bankroll_zeus', 20000) ON CONFLICT (key) DO NOTHING;"
    )
    cursor.execute("INSERT INTO prisma_config (key, value_int) VALUES ('ai_enabled', 1) ON CONFLICT (key) DO NOTHING;")
    cursor.execute(
        "INSERT INTO prisma_config (key, value_int) VALUES ('ensemble_enabled', 1) ON CONFLICT (key) DO NOTHING;"
    )

    # Table match_insights (cache des analyses IA par journée)
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS match_insights (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        journee INTEGER NOT NULL,
        equipe_dom_id INTEGER NOT NULL,
        equipe_ext_id INTEGER NOT NULL,
        prognosis VARCHAR(5),
        confidence REAL,
        analysis TEXT,
        advice TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, journee, equipe_dom_id, equipe_ext_id),
        FOREIGN KEY (session_id) REFERENCES sessions(id),
        FOREIGN KEY (equipe_dom_id) REFERENCES equipes(id),
        FOREIGN KEY (equipe_ext_id) REFERENCES equipes(id)
    );
    """
    )
    
    # Table ai_cycle_audits (Audit rétrospectif des performances IA)
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS ai_cycle_audits (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        start_journee INTEGER NOT NULL,
        end_journee INTEGER NOT NULL,
        report_json JSONB,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """
    )

    # Table risk_engine_logs (Logs des validations du Risk Engine)
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS risk_engine_logs (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        agent VARCHAR(20) NOT NULL,
        session_id INTEGER,
        bet_type VARCHAR(10),
        amount INTEGER,
        odds FLOAT,
        confidence FLOAT,
        validation_status VARCHAR(20),
        rejection_reason TEXT,
        resultat VARCHAR(50),
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """
    )

    # Table agent_cooldowns (Cooldowns entre paris par agent)
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS agent_cooldowns (
        agent VARCHAR(20) PRIMARY KEY,
        last_bet_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        bets_today INTEGER DEFAULT 0,
        last_reset DATE DEFAULT CURRENT_DATE
    );
    """
    )

    # Table prisma_safe_mode (Statut du mode SAFE de PRISMA)
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS prisma_safe_mode (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        active BOOLEAN DEFAULT FALSE,
        consecutive_losses INTEGER DEFAULT 0,
        activated_at TIMESTAMP,
        deactivated_at TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    );
    """
    )

    conn.commit()


def initialiser_db():
    """
    Initialise la base de données PostgreSQL
    """
    try:
        with get_db_connection() as conn:
            assert conn is not None, "La connexion à la base de données a échoué"
            create_new_schema(conn)

            cursor = conn.cursor()

            # Insertion des équipes
            cursor.executemany(
                "INSERT INTO equipes (nom) VALUES (%s) ON CONFLICT (nom) DO NOTHING", [(e,) for e in config.EQUIPES]
            )

            logger.info("Création des index PostgreSQL...")

            # Index pour performance
            indexes = [
                # Index existants
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
                "CREATE INDEX IF NOT EXISTS idx_match_insights_lookup ON match_insights(session_id, journee)",
                
                # Phase 1: Index sur les Foreign Keys manquants
                "CREATE INDEX IF NOT EXISTS idx_matches_equipe_dom ON matches(equipe_dom_id)",
                "CREATE INDEX IF NOT EXISTS idx_matches_equipe_ext ON matches(equipe_ext_id)",
                "CREATE INDEX IF NOT EXISTS idx_classement_equipe ON classement(equipe_id)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id)",
                "CREATE INDEX IF NOT EXISTS idx_historique_prediction ON historique_paris(prediction_id)",
                "CREATE INDEX IF NOT EXISTS idx_pari_items_prediction ON pari_multiple_items(prediction_id)",
                "CREATE INDEX IF NOT EXISTS idx_pari_items_pari ON pari_multiple_items(pari_multiple_id)",
                "CREATE INDEX IF NOT EXISTS idx_match_insights_equipes ON match_insights(equipe_dom_id, equipe_ext_id)",
                
                # Phase 1: Index pour les Requêtes Temporelles
                "CREATE INDEX IF NOT EXISTS idx_sessions_timestamp_debut ON sessions(timestamp_debut)",
                "CREATE INDEX IF NOT EXISTS idx_historique_timestamp_pari ON historique_paris(timestamp_pari)",
                "CREATE INDEX IF NOT EXISTS idx_pari_multiple_timestamp ON pari_multiple(timestamp_pari)",
                "CREATE INDEX IF NOT EXISTS idx_match_insights_timestamp ON match_insights(timestamp)",
                
                # Phase 2: Index pour les Filtrages Métier
                "CREATE INDEX IF NOT EXISTS idx_historique_strategie ON historique_paris(strategie)",
                "CREATE INDEX IF NOT EXISTS idx_pari_multiple_strategie ON pari_multiple(strategie)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_source ON predictions(source)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_resultat ON predictions(resultat)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(type_session)",
                
                # Phase 2: Index Composite Optimisé
                "CREATE INDEX IF NOT EXISTS idx_historique_session_journee ON historique_paris(session_id, journee)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_session_match ON predictions(session_id, match_id)",
                "CREATE INDEX IF NOT EXISTS idx_classement_session_journee ON classement(session_id, journee)",
                "CREATE INDEX IF NOT EXISTS idx_matches_session_status ON matches(session_id, status)",
                
                # Phase 3: Index pour les Agrégations
                "CREATE INDEX IF NOT EXISTS idx_historique_session_profit ON historique_paris(session_id, profit_net)",
                "CREATE INDEX IF NOT EXISTS idx_classement_points ON classement(points)",
                "CREATE INDEX IF NOT EXISTS idx_predictions_fiabilite ON predictions(fiabilite)",
                
                # Fix #9: Contrainte d'unicité sur les prédictions (anti-doublons)
                # Empêche PRISMA standard et amélioré de créer 2 prédictions pour le même match
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_predictions_unique_source ON predictions(session_id, match_id, source)",
                
                # Index pour tables Risk Engine
                "CREATE INDEX IF NOT EXISTS idx_risk_engine_logs_timestamp ON risk_engine_logs(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_risk_engine_logs_agent ON risk_engine_logs(agent)",
                "CREATE INDEX IF NOT EXISTS idx_risk_engine_logs_status ON risk_engine_logs(validation_status)",
                "CREATE INDEX IF NOT EXISTS idx_prisma_safe_mode_session ON prisma_safe_mode(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_prisma_safe_mode_active ON prisma_safe_mode(active)",
            ]

            for index_sql in indexes:
                cursor.execute(index_sql)

            conn.commit()
            logger.info(f"{len(indexes)} index créés avec succès.")
            logger.info("Base de données PostgreSQL initialisée (Architecture par Sessions v4).")

    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation PostgreSQL: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    initialiser_db()
