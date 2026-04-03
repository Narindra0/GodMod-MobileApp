import os
import sys
import logging
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from urllib.parse import quote_plus

# Ajouter le PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import BASE_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv(os.path.join(BASE_DIR, '.env'))

PG_HOST = os.getenv("PG_HOST")
PG_PORT = os.getenv("PG_PORT")
PG_DATABASE = os.getenv("PG_DATABASE")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")

def run_migration():
    if not all([PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD]):
        logger.error("Variables d'environnement DB manquantes.")
        return

    dsn = f"postgresql://{quote_plus(PG_USER)}:{quote_plus(PG_PASSWORD)}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    
    try:
        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        
        logger.info("Début de la migration V5 - Intelligence PRISMA.")

        # 1. Vérifier et ajouter les colonnes manquantes dans 'predictions'
        logger.info("1. Mise à jour de la table predictions...")
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'predictions';
        """)
        existing_columns = {row[0]: row[1] for row in cursor.fetchall()}

        if 'technical_details' not in existing_columns:
            logger.info(" -> Ajout de la colonne technical_details (JSONB)")
            cursor.execute("ALTER TABLE predictions ADD COLUMN technical_details JSONB;")
        elif existing_columns['technical_details'] == 'text':
            logger.info(" -> Conversion de technical_details de TEXT vers JSONB (USING CAST)")
            # Conversion si possible, sinon on ignore en cas d'erreur de cast. On suppose que ça contient du JSON valide
            try:
                cursor.execute("ALTER TABLE predictions ALTER COLUMN technical_details TYPE JSONB USING technical_details::jsonb;")
            except Exception as e:
                logger.warning(f"Impossible de convertir technical_details en JSONB: {e}. On garde la colonne en TEXT et on rollback transaction. On recommence.")
                conn.rollback()

        if 'ai_analysis' not in existing_columns:
            logger.info(" -> Ajout de la colonne ai_analysis (TEXT)")
            cursor.execute("ALTER TABLE predictions ADD COLUMN ai_analysis TEXT;")
            
        if 'ai_advice' not in existing_columns:
            logger.info(" -> Ajout de la colonne ai_advice (TEXT)")
            cursor.execute("ALTER TABLE predictions ADD COLUMN ai_advice TEXT;")

        # 2. Création de match_insights
        logger.info("2. Création de la table match_insights...")
        cursor.execute("""
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
        """)
        
        # Copier les données de groq_boosts vers match_insights si groq_boosts existe
        cursor.execute("SELECT to_regclass('public.groq_boosts');")
        if cursor.fetchone()[0] is not None:
            logger.info(" -> Migration des données de groq_boosts vers match_insights...")
            
            # On vérifie s'il y a des données
            cursor.execute("SELECT id, session_id, journee, equipe_dom_id, equipe_ext_id, raison, timestamp FROM groq_boosts;")
            rows = cursor.fetchall()
            
            if rows:
                import json
                count = 0
                for r in rows:
                    gid, sid, j, edom, eext, raison_str, ts = r
                    try:
                        data = json.loads(raison_str)
                        prognosis = data.get('prognosis', '')
                        conf = data.get('confidence', 0.0)
                        analysis = data.get('analysis', '')
                        advice = data.get('advice', '')
                    except:
                        prognosis = ''
                        conf = 0.0
                        analysis = str(raison_str)
                        advice = ''
                        
                    cursor.execute("""
                        INSERT INTO match_insights (session_id, journee, equipe_dom_id, equipe_ext_id, prognosis, confidence, analysis, advice, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (session_id, journee, equipe_dom_id, equipe_ext_id) DO NOTHING;
                    """, (sid, j, edom, eext, prognosis, conf, analysis, advice, ts))
                    count += 1
                logger.info(f" -> {count} lignes migrées de groq_boosts vers match_insights.")
                
            # Facultatif: on renomme l'ancienne table pour garder un backup de sécurité au lieu de Drop
            logger.info(" -> Renommage de groq_boosts en groq_boosts_legacy_backup")
            cursor.execute("ALTER TABLE groq_boosts RENAME TO groq_boosts_legacy_backup;")
            # Renommer les constraints pour eviter les problemes
            try:
                cursor.execute("SAVEPOINT rename_constraint;")
                cursor.execute("ALTER TABLE groq_boosts_legacy_backup RENAME CONSTRAINT groq_boosts_session_id_journee_equipe_dom_id_equi_key TO groq_boosts_legacy_backup_unique;")
                cursor.execute("RELEASE SAVEPOINT rename_constraint;")
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT rename_constraint;")
                
        # 3. Tables config et audits
        logger.info("3. Vérification des tables annexes...")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_cycle_audits (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL,
            start_journee INTEGER NOT NULL,
            end_journee INTEGER NOT NULL,
            report_json JSONB,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        """)
        
        # Essayer de caster report_json en JSONB si c'est TEXT
        cursor.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_name = 'ai_cycle_audits' AND column_name = 'report_json';
        """)
        audit_res = cursor.fetchone()
        if audit_res and audit_res[0] == 'text':
            try:
                cursor.execute("SAVEPOINT audit_json;")
                cursor.execute("ALTER TABLE ai_cycle_audits ALTER COLUMN report_json TYPE JSONB USING report_json::jsonb;")
                cursor.execute("RELEASE SAVEPOINT audit_json;")
            except Exception as e:
                logger.warning(f"Impossible de convertir report_json en JSONB: {e}. On annule cette sous-partie.")
                cursor.execute("ROLLBACK TO SAVEPOINT audit_json;")

        conn.commit()
        logger.info("✅ Migration terminée avec succès.")

    except Exception as e:
        logger.error(f"❌ Erreur lors de la migration: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
