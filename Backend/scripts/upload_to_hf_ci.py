"""
Upload des modèles PRISMA vers Hugging Face Spaces (version CI)
Usage: python scripts/upload_to_hf_ci.py
Ce script est conçu pour être exécuté dans GitHub Actions
"""

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent.parent.absolute()
MODELS_DIR = PROJECT_DIR / 'models' / 'prisma'

# Détecter si on est dans un repo Git (la racine avec .git)
GIT_ROOT = PROJECT_DIR
if PROJECT_DIR.name == 'Backend':
    # On est dans Backend/, la racine git est au-dessus
    git_parent = PROJECT_DIR.parent / '.git'
    if git_parent.exists():
        GIT_ROOT = PROJECT_DIR.parent
else:
    # On est peut-être déjà à la racine
    if not (PROJECT_DIR / '.git').exists():
        # Chercher le .git
        for parent in PROJECT_DIR.parents:
            if (parent / '.git').exists():
                GIT_ROOT = parent
                break

def get_required_files():
    """Retourne la liste des fichiers requis"""
    return [
        'xgboost_model.json',
        'xgboost_metadata.json', 
        'catboost_model.cbm',
        'catboost_metadata.json'
    ]

def check_models():
    """Vérifie que les modèles existent"""
    print("🔍 Vérification des modèles...")
    required = get_required_files()
    missing = []
    
    for file in required:
        path = MODELS_DIR / file
        if path.exists():
            size = path.stat().st_size
            print(f"  ✅ {file} ({size:,} bytes)")
        else:
            missing.append(file)
            print(f"  ❌ {file} MANQUANT")
    
    if missing:
        print(f"\n❌ {len(missing)} fichier(s) manquant(s)!")
        return False
    
    print(f"\n✅ Tous les modèles sont présents")
    return True

def upload_via_git():
    """Upload les modèles via git push vers HF"""
    space_id = os.environ.get('HF_SPACE_ID')
    token = os.environ.get('HF_TOKEN')
    
    if not space_id or not token:
        print("❌ HF_SPACE_ID ou HF_TOKEN non définis")
        return False
    
    repo_url = f"https://user:{token}@huggingface.co/spaces/{space_id}"
    commit_msg = f"Update PRISMA models - {datetime.now().strftime('%Y-%m-%d %H:%M')} [CI]"
    
    print(f"\n📤 Upload vers: {repo_url.replace(token, '***')}")
    print(f"📝 Message: {commit_msg}")
    
    try:
        # S'assurer que git lfs est configuré
        for pattern in ['Backend/models/**/*.json', 'Backend/models/**/*.cbm']:
            subprocess.run(
                ['git', 'lfs', 'track', pattern],
                cwd=GIT_ROOT,
                capture_output=True
            )
        
        # Stager les fichiers modèles
        print("\n➕ Ajout des fichiers...")
        for file in get_required_files():
            path = f"Backend/models/prisma/{file}"
            subprocess.run(
                ['git', 'add', '-f', path],
                cwd=GIT_ROOT,
                capture_output=True
            )
            print(f"  ✅ {file}")
        
        # Commit
        print("\n💾 Commit...")
        result = subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            cwd=GIT_ROOT,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"  ✅ Commit créé: {commit_msg}")
        else:
            print(f"  ℹ️  {result.stderr.strip() or 'Rien à committer'}")
        
        # Push vers HF
        print("\n🚀 Push vers Hugging Face...")
        result = subprocess.run(
            ['git', 'push', repo_url, 'HEAD:main'],
            cwd=GIT_ROOT,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            print("  ✅ Push réussi!")
            return True
        else:
            print(f"  ❌ Erreur push: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("  ❌ Timeout lors du push (>120s)")
        return False
    except Exception as e:
        print(f"  ❌ Erreur: {e}")
        return False

def main():
    print("="*60)
    print("📤 UPLOAD VERS HUGGING FACE (CI)")
    print("="*60)
    
    # Vérifier les modèles
    if not check_models():
        print("\n❌ Impossible de continuer: modèles manquants")
        return 1
    
    # Upload
    if upload_via_git():
        print("\n🎉 Upload terminé avec succès!")
        return 0
    else:
        print("\n❌ Échec de l'upload")
        return 1

if __name__ == '__main__':
    sys.exit(main())
