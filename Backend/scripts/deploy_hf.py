import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ajout du dossier parent au path pour les imports si nécessaire
sys.path.append(str(Path(__file__).parent.parent))

# Configuration du logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

try:
    from huggingface_hub import HfApi
except ImportError:
    logger.error("La bibliothèque 'huggingface-hub' n'est pas installée.")
    logger.info("Veuillez lancer : pip install huggingface-hub")
    sys.exit(1)

def deploy():
    # Charger les variables d'environnement
    # On cherche le .env au niveau du dossier Backend (parent de scripts)
    backend_root = Path(__file__).parent.parent
    env_path = backend_root / ".env"
    load_dotenv(env_path)

    token = os.getenv("HF_TOKEN")
    repo_id = os.getenv("HF_SPACE_ID", "JacknotDaniel/godmod-backend")

    if not token or token.startswith("hf_..."):
        logger.error("Le token Hugging Face (HF_TOKEN) est manquant ou non configuré dans .env")
        logger.info("Veuillez créer un token 'Write' sur https://huggingface.co/settings/tokens")
        return

    api = HfApi()

    logger.info(f"Début du déploiement vers le Space : {repo_id}")
    
    # Patterns à ignorer lors de l'upload
    ignore_patterns = [
        ".env",
        "__pycache__",
        "*.pyc",
        "data/*",
        "logs/*",
        "catboost_info/*",
        ".git/*",
        ".github/*",
        ".antigravityignore",
        ".gemini/*",
        "node_modules/*"
    ]

    try:
        # On uploade tout le dossier Backend vers la racine du Space
        # delete_patterns supprime les fichiers absents du local, sauf les modèles Zeus et Prisma
        api.upload_folder(
            folder_path=str(backend_root),
            repo_id=repo_id,
            repo_type="space",
            token=token,
            ignore_patterns=ignore_patterns,
            commit_message="Mise à jour GODMOD - Fix Build 128"
        )
        logger.info("✅ Déploiement réussi !")
        logger.info(f"Votre application est accessible ici : https://huggingface.co/spaces/{repo_id}")
    except Exception as e:
        logger.error(f"❌ Erreur lors du déploiement : {e}")

if __name__ == "__main__":
    deploy()
