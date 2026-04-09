"""
Script de mise à jour du modèle ZEUS v2 depuis Hugging Face Models.
À exécuter APRÈS que Colab a pushé zeus_v2_best.zip sur HF Models.

Usage:
    python scripts/update_zeus_from_hf.py

Ce script :
  1. Télécharge zeus_v2_best.zip depuis JacknotDaniel/zeus-models
  2. Sauvegarde l'ancien best_model.zip en .bak
  3. Place le nouveau modèle v2 dans models/zeus/best/best_model.zip
  4. Redéploie le HF Space automatiquement (optionnel)
"""
import os
import shutil
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).parent.parent
BEST_MODEL_DIR = BACKEND_ROOT / "models" / "zeus" / "best"
BEST_MODEL_PATH = BEST_MODEL_DIR / "best_model.zip"
HF_REPO_MODELS = "JacknotDaniel/zeus-models"
HF_FILE_V2 = "zeus_v2_best.zip"


def download_v2_model(token: str) -> Path:
    """Télécharge le modèle v2 depuis HF Models."""
    from huggingface_hub import hf_hub_download

    logger.info(f"Téléchargement de {HF_FILE_V2} depuis {HF_REPO_MODELS}...")
    local_path = hf_hub_download(
        repo_id=HF_REPO_MODELS,
        filename=HF_FILE_V2,
        repo_type="model",
        token=token,
        local_dir=str(BACKEND_ROOT / "models" / "zeus"),
    )
    logger.info(f"  ✅ Téléchargé : {local_path}")
    return Path(local_path)


def swap_model(downloaded_path: Path):
    """Remplace le best_model.zip par le nouveau modèle v2 (swap atomique)."""
    BEST_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Backup de l'ancien modèle
    if BEST_MODEL_PATH.exists():
        bak_path = BEST_MODEL_PATH.with_suffix(".zip.bak")
        shutil.copy2(BEST_MODEL_PATH, bak_path)
        logger.info(f"  Ancien modèle sauvegardé : {bak_path}")

    shutil.copy2(downloaded_path, BEST_MODEL_PATH)
    logger.info(f"  ✅ Modèle v2 activé : {BEST_MODEL_PATH}")


def redeploy_hf_space(token: str):
    """Redéploie le HF Space avec le nouveau modèle (optionnel)."""
    response = input("\nRedéployer le HF Space maintenant ? [o/N] : ").strip().lower()
    if response != "o":
        logger.info("Redéploiement ignoré. Lancez manuellement : python scripts/deploy_hf.py")
        return

    logger.info("Lancement du redéploiement HF Space...")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "deploy_hf.py")],
        cwd=str(BACKEND_ROOT),
    )
    if result.returncode == 0:
        logger.info("✅ HF Space redéployé avec succès !")
    else:
        logger.error("Erreur lors du redéploiement. Lancez manuellement : python scripts/deploy_hf.py")


def main():
    load_dotenv(BACKEND_ROOT / ".env")
    token = os.getenv("HF_TOKEN", "")

    logger.info("=" * 55)
    logger.info("ZEUS v2 — Mise à jour depuis Hugging Face Models")
    logger.info("=" * 55)

    if not token or token.startswith("hf_..."):
        logger.error("HF_TOKEN manquant dans .env")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi
    except ImportError:
        logger.error("huggingface-hub non installé : pip install huggingface-hub")
        sys.exit(1)

    # Vérifier que le fichier v2 existe sur HF
    api = HfApi()
    try:
        files = api.list_repo_files(repo_id=HF_REPO_MODELS, repo_type="model", token=token)
        if HF_FILE_V2 not in list(files):
            logger.error(
                f"{HF_FILE_V2} introuvable dans {HF_REPO_MODELS}.\n"
                "Assurez-vous d'avoir terminé l'entraînement Colab et pushé le modèle."
            )
            sys.exit(1)
    except Exception as e:
        logger.error(f"Impossible de vérifier HF Models : {e}")
        sys.exit(1)

    downloaded = download_v2_model(token)
    swap_model(downloaded)
    redeploy_hf_space(token)

    logger.info("=" * 55)
    logger.info("✅ ZEUS v2 est maintenant actif en production !")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
