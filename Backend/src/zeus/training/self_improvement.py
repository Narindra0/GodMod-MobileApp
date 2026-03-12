"""
Orchestrateur de la boucle d'auto-amélioration (Self-Improvement) de ZEUS.
Gère le trigger, l'entraînement global, et la promotion du modèle.
"""

import time
import sqlite3
import os
import logging
from .trainer import train_zeus_agent
from ..database.queries import check_new_season_available, get_last_training_metadata
from ..models.comparison import evaluer_robustesse, doit_promouvoir, deployer_modele
from ..environment.betting_env import BettingEnv
from ...core import config
from stable_baselines3 import PPO

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ZEUS_SELF_IMPROVEMENT")


def enter_deep_sleep():
    """Active le mode sommeil profond pour ZEUS."""
    logger.info("💤 ZEUS Entre en Sommeil Profond...")
    config.ZEUS_DEEP_SLEEP = True


def exit_deep_sleep():
    """Désactive le mode sommeil profond."""
    logger.info("🌅 ZEUS se réveille.")
    config.ZEUS_DEEP_SLEEP = False


# Configuration
DEFAULT_TRAINING_TIMESTEPS = 500_000
IMPROVEMENT_POLL_INTERVAL = 3600  # 1 heure

# Métriques par défaut réalistes
DEFAULT_OLD_METRICS = {
    'avg_roi': -5.0, 'std_roi': 15.0, 'survival_rate': 0.85
}


def trigger_zeus_improvement(db_path: str = None):
    """
    Exécute un cycle complet d'amélioration ZEUS.
    Peut être appelé manuellement ou via un trigger.
    """
    current_db_path = db_path or config.DB_NAME
    try:
        conn = sqlite3.connect(current_db_path)
        
        if check_new_season_available(conn):
            logger.info("🔔 Nouvelle saison détectée ! Lancement du cycle d'amélioration...")
            
            # 1. Sommeil Profond
            enter_deep_sleep()
            
            # 2. Récupérer métadonnées actuelles
            last_meta = get_last_training_metadata(conn)
            old_model_path = config.ZEUS_MODEL_PATH
            
            # 3. Entraînement Global intensif
            # On utilise une version incrémentée
            try:
                version_num = float(last_meta['version'].replace('ZEUS_v', ''))
                new_version = f"ZEUS_v{version_num + 0.1:.1f}"
            except:
                new_version = "ZEUS_v1.0"
            
            logger.info(f"🏋️ Entraînement de la version {new_version} sur tout l'historique...")
            new_model = train_zeus_agent(
                db_path=current_db_path,
                n_timesteps=DEFAULT_TRAINING_TIMESTEPS,
                version_ia=new_version
            )
            
            # 4. Évaluation et Comparaison
            logger.info("📊 Comparaison des performances...")
            
            # Env d'évaluation (dernière saison)
            eval_env = BettingEnv(db_path=current_db_path, mode='eval')
            
            # Métriques nouveau modèle
            new_metrics = evaluer_robustesse(new_model, eval_env)
            
            # Métriques ancien modèle (si existant)
            old_metrics = DEFAULT_OLD_METRICS.copy()
            
            if os.path.exists(old_model_path):
                old_model = PPO.load(old_model_path)
                old_metrics = evaluer_robustesse(old_model, eval_env)
            
            # 5. Promotion
            if doit_promouvoir(new_metrics, old_metrics):
                logger.info(f"🏆 Promotion de la version {new_version} !")
                promotion_path = os.path.join(config.MODELS_DIR, "zeus", f"zeus_final_{new_version}.zip")
                deployer_modele(promotion_path)
            else:
                logger.info("❌ Le nouveau modèle n'a pas surpassé l'ancien. Maintien du modèle actuel.")
            
            # 6. Réveil
            exit_deep_sleep()
        else:
            logger.info("ℹ️ Pas assez de nouvelles données pour un réentraînement (besoin d'une saison complète).")
            
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du cycle d'amélioration : {e}")
        exit_deep_sleep() # Sécurité


def run_self_improvement_loop(db_path: str = None):
    """
    Boucle principale de monitoring pour l'auto-amélioration.
    """
    current_db_path = db_path or config.DB_NAME
    logger.info(f"🔭 Démarrage du moniteur d'auto-amélioration ZEUS sur {current_db_path} (Polling horaire)...")
    
    while True:
        trigger_zeus_improvement(current_db_path)
        # Vérification toutes les heures
        time.sleep(IMPROVEMENT_POLL_INTERVAL)


if __name__ == "__main__":
    run_self_improvement_loop()
