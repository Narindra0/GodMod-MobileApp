import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from src.core.system import config
from src.zeus.training.trainer import TrainingConfig, train_zeus_agent


def main():
    parser = argparse.ArgumentParser(description="Entraîner l'agent ZEUS de Reinforcement Learning")
    parser.add_argument("--db", type=str, default=config.DB_NAME, help="Chemin vers la base de données SQLite")
    parser.add_argument("--timesteps", type=int, default=1_000_000, help="Nombre total de timesteps d'entraînement")
    parser.add_argument(
        "--checkpoint-freq", type=int, default=50_000, help="Fréquence de sauvegarde des checkpoints (en steps)"
    )
    parser.add_argument("--eval-freq", type=int, default=10_000, help="Fréquence d'évaluation (en steps)")
    parser.add_argument("--learning-rate", type=float, default=3e-4, help="Taux d'apprentissage")
    parser.add_argument("--version", type=str, default="v2.0", help="Version du modèle (ex: v2.0)")
    parser.add_argument(
        "--journee-debut-train", type=int, help="Première journée utilisée pour l'entraînement (mode manuel)"
    )
    parser.add_argument(
        "--journee-fin-train", type=int, help="Dernière journée utilisée pour l'entraînement (mode manuel)"
    )
    parser.add_argument(
        "--journee-debut-eval", type=int, help="Première journée utilisée pour l'évaluation (mode manuel)"
    )
    parser.add_argument(
        "--journee-fin-eval", type=int, help="Dernière journée utilisée pour l'évaluation (mode manuel)"
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
    if args.journee_debut_train is not None:
        print(f"  - Train jours:     {args.journee_debut_train}" f" -> {args.journee_fin_train}")
        print(f"  - Eval jours:      {args.journee_debut_eval}" f" -> {args.journee_fin_eval}")
    print()

    train_zeus_agent(
        TrainingConfig(
            db_path=args.db,
            n_timesteps=args.timesteps,
            checkpoint_freq=args.checkpoint_freq,
            eval_freq=args.eval_freq,
            learning_rate=args.learning_rate,
            version_ia=args.version,
            journee_debut_train=args.journee_debut_train,
            journee_fin_train=args.journee_fin_train,
            journee_debut_eval=args.journee_debut_eval,
            journee_fin_eval=args.journee_fin_eval,
        )
    )
    print("\n✅ Entraînement terminé avec succès!")


if __name__ == "__main__":
    main()
