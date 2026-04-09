"""
PHASE 0 — Backup ZEUS v1
Sauvegarde le modèle actuel AVANT toute modification ZEUS v2.
Usage: python scripts/backup_zeus_v1.py
"""
import os
import shutil
import subprocess
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).parent.parent
BEST_MODEL_PATH = BACKEND_ROOT / "models" / "zeus" / "best" / "best_model.zip"
BACKUP_DIR = BACKEND_ROOT / "models" / "zeus" / "backup_v1"
BACKUP_PATH = BACKUP_DIR / "zeus_v1_backup.zip"
HF_REPO_MODELS = "JacknotDaniel/zeus-models"


def backup_local() -> bool:
    if not BEST_MODEL_PATH.exists():
        logger.error(f"Modèle introuvable : {BEST_MODEL_PATH}")
        logger.error("Assurez-vous que ./models/zeus/best/best_model.zip existe.")
        return False
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BEST_MODEL_PATH, BACKUP_PATH)
    logger.info(f"✅ Backup local : {BACKUP_PATH}")
    # Copier aussi les zeus_final_*.zip
    for src in (BACKEND_ROOT / "models" / "zeus").glob("zeus_final_*.zip"):
        shutil.copy2(src, BACKUP_DIR / src.name)
        logger.info(f"   ↳ {src.name} sauvegardé")
    return True


def create_git_tag():
    try:
        result = subprocess.run(
            ["git", "tag", "-a", "zeus-v1-stable", "-m", "ZEUS v1 stable — avant migration v2"],
            cwd=str(BACKEND_ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.info("✅ Tag git créé : zeus-v1-stable")
        else:
            logger.warning(f"Tag git (non bloquant) : {result.stderr.strip()}")
    except FileNotFoundError:
        logger.warning("Git non disponible — tag ignoré (non bloquant).")


def push_to_hf():
    load_dotenv(BACKEND_ROOT / ".env")
    token = os.getenv("HF_TOKEN", "")
    if not token or token.startswith("hf_..."):
        logger.warning("HF_TOKEN non configuré — push HF ignoré.")
        logger.info("   → Modèle sauvegardé localement dans models/zeus/backup_v1/")
        return
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        # Créer le repo de modèles si nécessaire (séparé du Space)
        try:
            api.create_repo(
                repo_id=HF_REPO_MODELS,
                repo_type="model",
                exist_ok=True,
                token=token,
                private=False,
            )
            logger.info(f"Repo HF prêt : https://huggingface.co/{HF_REPO_MODELS}")
        except Exception as e:
            logger.warning(f"create_repo (non bloquant) : {e}")
        # Upload le backup
        api.upload_file(
            path_or_fileobj=str(BACKUP_PATH),
            path_in_repo="zeus_v1_backup.zip",
            repo_id=HF_REPO_MODELS,
            repo_type="model",
            token=token,
            commit_message="Backup ZEUS v1 — avant migration v2",
        )
        logger.info(f"✅ Backup poussé : https://huggingface.co/{HF_REPO_MODELS}")
    except ImportError:
        logger.error("huggingface-hub non installé : pip install huggingface-hub")
    except Exception as e:
        logger.error(f"Erreur HF : {e}")
        logger.info("   → Le backup local reste valide.")


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("ZEUS v1 — BACKUP COMPLET")
    logger.info("=" * 55)
    if not backup_local():
        sys.exit(1)
    create_git_tag()
    push_to_hf()
    logger.info("=" * 55)
    logger.info("✅ Backup terminé — ZEUS v1 est sécurisé.")
    logger.info("   Vous pouvez maintenant modifier les fichiers v2.")
    logger.info("=" * 55)
