import time
import os
import logging
from .trainer import train_zeus_agent
from ..database.queries import check_new_season_available, get_last_training_metadata
from ..models.comparison import evaluer_robustesse, doit_promouvoir, deployer_modele
from ..environment.betting_env import BettingEnv
from ...core import config
from stable_baselines3 import PPO
from ...core.database import get_db_connection
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ZEUS_SELF_IMPROVEMENT")
def enter_deep_sleep():
    logger.info("💤 ZEUS Entre en Sommeil Profond...")
    config.ZEUS_DEEP_SLEEP = True
def exit_deep_sleep():
    logger.info("🌅 ZEUS se réveille.")
    config.ZEUS_DEEP_SLEEP = False
DEFAULT_TRAINING_TIMESTEPS = 500_000
IMPROVEMENT_POLL_INTERVAL = 3600
DEFAULT_OLD_METRICS = {
    'avg_roi': -5.0, 'std_roi': 15.0, 'survival_rate': 0.85
}
def trigger_zeus_improvement(db_path: str = None):
    current_db_path = db_path or config.DB_NAME
    try:
        with get_db_connection(write=True) as conn:
            if check_new_season_available(conn):
                logger.info("🔔 Nouvelle saison détectée ! Lancement du cycle d'amélioration...")
                enter_deep_sleep()
                last_meta = get_last_training_metadata(conn)
                old_model_path = config.ZEUS_MODEL_PATH
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
                logger.info("📊 Comparaison des performances...")
                eval_env = BettingEnv(db_path=current_db_path, mode='eval')
                new_metrics = evaluer_robustesse(new_model, eval_env)
                old_metrics = DEFAULT_OLD_METRICS.copy()
                if os.path.exists(old_model_path):
                    old_model = PPO.load(old_model_path)
                    old_metrics = evaluer_robustesse(old_model, eval_env)
                if doit_promouvoir(new_metrics, old_metrics):
                    logger.info(f"🏆 Promotion de la version {new_version} !")
                    promotion_path = os.path.join(config.MODELS_DIR, "zeus", f"zeus_final_{new_version}.zip")
                    deployer_modele(promotion_path)
                else:
                    logger.info("❌ Le nouveau modèle n'a pas surpassé l'ancien. Maintien du modèle actuel.")
                exit_deep_sleep()
            else:
                logger.info("ℹ️ Pas assez de nouvelles données pour un réentraînement (besoin d'une saison complète).")
    except Exception as e:
        logger.error(f"❌ Erreur lors du cycle d'amélioration : {e}")
        exit_deep_sleep()
def run_self_improvement_loop(db_path: str = None):
    current_db_path = db_path or config.DB_NAME
    logger.info(f"🔭 Démarrage du moniteur d'auto-amélioration ZEUS sur {current_db_path} (Polling horaire)...")
    while True:
        trigger_zeus_improvement(current_db_path)
        time.sleep(IMPROVEMENT_POLL_INTERVAL)
