"""
Script de lancement pour la boucle d'auto-amélioration de ZEUS.
Ce script surveille la base de données et lance un réentraînement dès qu'une saison est complète.
"""

import sys
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.zeus.training.self_improvement import run_self_improvement_loop

if __name__ == "__main__":
    print("🏛️  ZEUS - Démarrage du système d'Auto-Amélioration Rapide")
    try:
        run_self_improvement_loop()
    except KeyboardInterrupt:
        print("\n👋 Arrêt du système.")
        sys.exit(0)
