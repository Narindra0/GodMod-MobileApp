import sys
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from src.zeus.training.self_improvement import run_self_improvement_loop
if __name__ == "__main__":
    print("🏛️  ZEUS - Démarrage du système d'Auto-Amélioration Rapide")
    try:
        run_self_improvement_loop()
    except KeyboardInterrupt:
        print("\n👋 Arrêt du système.")
        sys.exit(0)
