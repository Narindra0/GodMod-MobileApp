"""
Export des données d'entraînement depuis Neon vers des CSV locaux.
Utilise 2 requêtes SQL max — résultats mis en cache dans data/export/.

Usage:
    python scripts/export_training_data.py

Les CSV générés sont uploadés sur Google Colab pour l'entraînement
sans surcharger la base Neon pendant les 2M timesteps.
"""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).parent.parent
EXPORT_DIR = BACKEND_ROOT / "data" / "export"


def main():
    logger.info("=" * 55)
    logger.info("Export données Neon → CSV pour Google Colab")
    logger.info("=" * 55)

    try:
        import pandas as pd
        from src.core.database import get_db_connection
    except ImportError as e:
        logger.error(f"Dépendance manquante : {e}")
        logger.error("Installez : pip install pandas psycopg2-binary")
        sys.exit(1)

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    with get_db_connection(write=False) as conn:
        import psycopg2.extras
        conn.cursor_factory = None  # On utilise pandas qui gère ça directement

        import psycopg2

        logger.info("Requête 1/2 : Export des matchs TERMINE...")
        matches_query = """
            SELECT
                m.id,
                m.journee,
                m.equipe_dom_id,
                m.equipe_ext_id,
                e_dom.nom  AS equipe_dom_nom,
                e_ext.nom  AS equipe_ext_nom,
                m.cote_1,
                m.cote_x,
                m.cote_2,
                m.score_dom,
                m.score_ext,
                m.status,
                m.session_id
            FROM matches m
            JOIN equipes e_dom ON m.equipe_dom_id = e_dom.id
            JOIN equipes e_ext ON m.equipe_ext_id = e_ext.id
            WHERE m.status = 'TERMINE'
              AND m.cote_1 IS NOT NULL
              AND m.cote_x IS NOT NULL
              AND m.cote_2 IS NOT NULL
            ORDER BY m.session_id, m.journee, m.id
        """
        df_matches = pd.read_sql(matches_query, conn.connection
                                  if hasattr(conn, 'connection') else conn)
        matches_path = EXPORT_DIR / "matches_training.csv"
        df_matches.to_csv(matches_path, index=False)
        logger.info(f"  ✅ {len(df_matches)} matchs exportés → {matches_path}")

        logger.info("Requête 2/2 : Export du classement...")
        classement_query = """
            SELECT
                session_id,
                equipe_id,
                journee,
                position,
                points,
                forme
            FROM classement
            ORDER BY session_id, journee, equipe_id
        """
        df_classement = pd.read_sql(classement_query, conn.connection
                                     if hasattr(conn, 'connection') else conn)
        classement_path = EXPORT_DIR / "classement_training.csv"
        df_classement.to_csv(classement_path, index=False)
        logger.info(f"  ✅ {len(df_classement)} lignes classement exportées → {classement_path}")

    logger.info("")
    logger.info("=" * 55)
    logger.info("Export terminé ! Prochaines étapes :")
    logger.info("")
    logger.info("  1. Ouvrez Google Colab")
    logger.info("  2. Uploadez ces 2 fichiers CSV :")
    logger.info(f"       {matches_path}")
    logger.info(f"       {classement_path}")
    logger.info("  3. Uploadez aussi colab/zeus_v2_training.ipynb")
    logger.info("  4. Lancez l'entraînement !")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
