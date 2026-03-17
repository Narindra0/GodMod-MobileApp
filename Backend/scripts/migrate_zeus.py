import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.core import database
def main():
    print("=" * 60)
    print("🏛️  ZEUS - Migration de la base de données")
    print("=" * 60)
    print("\n📊 Initialisation des tables ZEUS...")
    print("   - sessions")
    print("   - historique_paris")
    database.initialiser_db()
    print("\n✅ Migration terminée avec succès!")
    print("=" * 60)
if __name__ == "__main__":
    main()
