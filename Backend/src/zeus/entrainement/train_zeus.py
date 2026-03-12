"""
Script d'entraînement principal pour l'agent ZEUS.

Usage:
    python train_zeus.py --timesteps 1000000 --eval-freq 10000
"""

import argparse
import sys
from pathlib import Path

# Ajouter le répertoire racine au path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.zeus.training.trainer import train_zeus_agent
from src.core import config


def main():
    parser = argparse.ArgumentParser(
        description="Entraîner l'agent ZEUS de Reinforcement Learning"
    )
    
    parser.add_argument(
        '--db',
        type=str,
        default=config.DB_NAME,
        help='Chemin vers la base de données SQLite'
    )
    
    parser.add_argument(
        '--timesteps',
        type=int,
        default=1_000_000,
        help='Nombre total de timesteps d\'entraînement'
    )
    
    parser.add_argument(
        '--checkpoint-freq',
        type=int,
        default=50_000,
        help='Fréquence de sauvegarde des checkpoints (en steps)'
    )
    
    parser.add_argument(
        '--eval-freq',
        type=int,
        default=10_000,
        help='Fréquence d\'évaluation (en steps)'
    )
    
    parser.add_argument(
        '--learning-rate',
        type=float,
        default=3e-4,
        help='Taux d\'apprentissage'
    )
    
    parser.add_argument(
        '--version',
        type=str,
        default='v1.0',
        help='Version du modèle'
    )
    
    args = parser.parse_args()
    
    print("\n🏛️  ZEUS - Agent de Reinforcement Learning")
    print("Configuration:")
    print(f"  - Database:        {args.db}")
    print(f"  - Timesteps:       {args.timesteps:,}")
    print(f"  - Checkpoint freq: {args.checkpoint_freq:,}")
    print(f"  - Eval freq:       {args.eval_freq:,}")
    print(f"  - Learning rate:   {args.learning_rate}")
    print(f"  - Version:         {args.version}")
    print()
    
    # Entraîner
    model = train_zeus_agent(
        db_path=args.db,
        n_timesteps=args.timesteps,
        checkpoint_freq=args.checkpoint_freq,
        eval_freq=args.eval_freq,
        learning_rate=args.learning_rate,
        version_ia=args.version
    )
    
    print("\n✅ Entraînement terminé avec succès!")
    

if __name__ == "__main__":
    main()
