"""
Upload des modèles PRISMA vers Hugging Face Spaces
Usage: python scripts/upload_models_hf.py [--message "Update models"]

Ce script :
1. Vérifie les modèles locaux entraînés
2. Les push vers le repo HF Spaces via git
3. Déclenche un rebuild du space (optionnel)
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Répertoire du projet
PROJECT_DIR = Path(__file__).parent.parent.absolute()
MODELS_DIR = PROJECT_DIR / 'models' / 'prisma'


def check_models():
    """Vérifie que les modèles existent"""
    print("🔍 Vérification des modèles...")
    
    required_files = [
        'xgboost_model.json',
        'xgboost_metadata.json', 
        'catboost_model.cbm',
        'catboost_metadata.json'
    ]
    
    found = []
    missing = []
    
    for file in required_files:
        path = MODELS_DIR / file
        if path.exists():
            size = path.stat().st_size
            found.append((file, size))
            print(f"  ✅ {file} ({size:,} bytes)")
        else:
            missing.append(file)
            print(f"  ❌ {file} MANQUANT")
    
    if missing:
        print(f"\n⚠️  {len(missing)} fichier(s) manquant(s)!")
        return False
    
    print(f"\n✅ Tous les modèles sont présents ({len(found)} fichiers)")
    return True


def get_hf_space_id():
    """Récupère l'ID du space HF depuis .env"""
    env_file = PROJECT_DIR / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.startswith('HF_SPACE_ID='):
                    return line.split('=')[1].strip()
    return None


def upload_via_git(message="Update PRISMA models"):
    """Upload les modèles via git push"""
    space_id = get_hf_space_id()
    if not space_id:
        print("❌ HF_SPACE_ID non trouvé dans .env")
        return False
    
    repo_url = f"https://huggingface.co/spaces/{space_id}"
    
    print(f"\n📤 Upload vers: {repo_url}")
    print(f"📝 Message: {message}")
    
    try:
        # Vérifier si git lfs est configuré
        result = subprocess.run(
            ['git', 'lfs', 'track'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True
        )
        
        # S'assurer que les modèles sont trackés par LFS
        for pattern in ['models/**/*.json', 'models/**/*.cbm']:
            subprocess.run(
                ['git', 'lfs', 'track', pattern],
                cwd=PROJECT_DIR,
                capture_output=True
            )
        
        # Configurer git si nécessaire
        subprocess.run(['git', 'config', 'user.email', 'training@godmod.local'], 
                      cwd=PROJECT_DIR, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Training Bot'], 
                      cwd=PROJECT_DIR, capture_output=True)
        
        # Add les modèles
        print("\n➕ Ajout des fichiers au staging...")
        for file in ['xgboost_model.json', 'xgboost_metadata.json',
                     'catboost_model.cbm', 'catboost_metadata.json']:
            path = f"models/prisma/{file}"
            result = subprocess.run(
                ['git', 'add', path],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"  ✅ {file}")
            else:
                print(f"  ⚠️  {file} (peut-être déjà tracké)")
        
        # Commit
        print("\n💾 Commit...")
        result = subprocess.run(
            ['git', 'commit', '-m', message],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"  ✅ Commit créé")
        else:
            print(f"  ℹ️  {result.stderr or 'Rien à committer'}")
        
        # Push
        print("\n🚀 Push vers Hugging Face...")
        result = subprocess.run(
            ['git', 'push', 'origin', 'main'],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("  ✅ Push réussi!")
            print(f"\n🌐 Voir les changements: {repo_url}")
            return True
        else:
            print(f"  ❌ Erreur push: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False


def rebuild_space():
    """Déclenche un rebuild du space HF (via API)"""
    print("\n🔄 Rebuild du Space...")
    
    try:
        import requests
        
        space_id = get_hf_space_id()
        token = os.getenv('HF_TOKEN')
        
        if not token:
            print("  ⚠️  HF_TOKEN non défini, rebuild ignoré")
            return False
        
        url = f"https://huggingface.co/api/spaces/{space_id}/restart"
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.post(url, headers=headers)
        
        if response.status_code == 200:
            print("  ✅ Rebuild déclenché!")
            return True
        else:
            print(f"  ⚠️  Erreur rebuild: {response.status_code}")
            return False
            
    except ImportError:
        print("  ⚠️  requests non installé, rebuild ignoré")
        return False
    except Exception as e:
        print(f"  ⚠️  Erreur: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Upload des modèles vers HF Spaces')
    parser.add_argument('--message', type=str, 
                        default=f"Update PRISMA models - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        help='Message de commit')
    parser.add_argument('--no-rebuild', action='store_true',
                        help='Ne pas rebuild le space après upload')
    parser.add_argument('--dry-run', action='store_true',
                        help='Vérifier sans upload')
    
    args = parser.parse_args()
    
    print("="*60)
    print("📤 UPLOAD DES MODÈLES VERS HUGGING FACE")
    print("="*60)
    
    # Vérifier les modèles
    if not check_models():
        print("\n❌ Impossible de continuer: modèles manquants")
        print("\n💡 Lance d'abord l'entraînement:")
        print("   python scripts/local_training.py --force")
        return 1
    
    if args.dry_run:
        print("\n🏃 Dry-run: upload non effectué")
        return 0
    
    # Upload
    if upload_via_git(args.message):
        if not args.no_rebuild:
            rebuild_space()
        print("\n🎉 Upload terminé avec succès!")
        return 0
    else:
        print("\n❌ Échec de l'upload")
        return 1


if __name__ == '__main__':
    sys.exit(main())
