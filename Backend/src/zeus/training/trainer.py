import os
from dataclasses import dataclass
from typing import Optional

from ...core import config
from ...core.database import get_db_connection
from ..environment.betting_env import BettingEnv
from ..models.ppo_agent import CallbackConfig, PPOConfig, create_callbacks, create_ppo_agent


@dataclass(frozen=True)
class TrainingConfig:
    db_path: str | None = None
    n_timesteps: int = 1_000_000
    checkpoint_freq: int = 50_000
    eval_freq: int = 10_000
    learning_rate: float = 3e-4
    version_ia: str = "v1.0"
    journee_debut_train: Optional[int] = None
    journee_fin_train: Optional[int] = None
    journee_debut_eval: Optional[int] = None
    journee_fin_eval: Optional[int] = None


def _select_completed_training_session(db_path: str) -> Optional[int]:
    """
    Sélectionne une session dont les matches couvrent au moins les journées 1 à 37 (incluses).
    On ne considère que ces sessions "complètes" pour entraîner ZEUS.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.id
            FROM sessions s
            JOIN matches m ON m.session_id = s.id
            WHERE m.status = 'TERMINE'
            GROUP BY s.id
            HAVING COUNT(DISTINCT CASE WHEN m.journee BETWEEN 1 AND 37 THEN m.journee END) = 37
            ORDER BY s.id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return row["id"] if row else None


def train_zeus_agent(cfg: Optional[TrainingConfig] = None):
    print("=" * 60)
    print("ZEUS - Entrainement de l'agent RL")
    print("=" * 60)
    cfg = cfg or TrainingConfig()
    current_db_path = cfg.db_path or config.DB_NAME

    # On selectionne une session "complete" (jours 1 a 37 termines) pour l'entrainement.
    feature_session_id = _select_completed_training_session(current_db_path)
    if feature_session_id is None:
        raise ValueError(
            "Aucune session complete trouvee pour l'entrainement ZEUS.\n"
            "Assure-toi d'avoir au moins une session avec des matches TERMINE "
            "pour toutes les journees 1 a 37."
        )
    print(
        f"Utilisation de la session {feature_session_id} "
        "pour les donnees de matches/classement (session complete 1-37)."
    )

    # Determination automatique des plages de journees si non precisees (Mode Flex).
    if cfg.journee_debut_train is None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # IMPORTANT : on ne considere que les matches de la session selectionnee.
            cursor.execute(
                "SELECT DISTINCT journee FROM matches "
                "WHERE status = 'TERMINE' AND session_id = %s "
                "ORDER BY journee",
                (feature_session_id,),
            )
            all_journees = [row["journee"] for row in cursor.fetchall()]

            if len(all_journees) < 10:
                conn.close()
                raise ValueError(
                    f"Pas assez de donnees dans {current_db_path}. "
                    f"Trouve {len(all_journees)} journees, besoin d'au moins 10."
                )

            split_idx = int(len(all_journees) * 0.8)
            journee_debut_train = all_journees[0]
            journee_fin_train = all_journees[split_idx - 1]
            journee_debut_eval = all_journees[split_idx]
            journee_fin_eval = all_journees[-1]

            # Stats basiques sur la distribution des donnees (nombre de matches).
            def count_matches(j_start: int, j_end: int) -> int:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM matches " "WHERE status = 'TERMINE' AND journee BETWEEN %s AND %s",
                    (j_start, j_end),
                )
                result = cursor.fetchone()
                return result["count"] if result else 0

            n_matches_train = count_matches(journee_debut_train, journee_fin_train)
            n_matches_eval = count_matches(journee_debut_eval, journee_fin_eval)

            print(f"Mode Flex: {len(all_journees)} journees TERMINE dans la base")
            print(f"Train: Journees {journee_debut_train} a {journee_fin_train} " f"({n_matches_train} matches)")
            print(f"Eval:  Journees {journee_debut_eval} a {journee_fin_eval} " f"({n_matches_eval} matches)")
    else:
        print(
            f"Plages manuelles: "
            f"Train J{cfg.journee_debut_train}-{cfg.journee_fin_train}, "
            f"Eval J{cfg.journee_debut_eval}-{cfg.journee_fin_eval}"
        )

    print("\nCreation des environnements...")
    train_env = BettingEnv(
        capital_initial=config.DEFAULT_BANKROLL,
        journee_debut=journee_debut_train if cfg.journee_debut_train is None else cfg.journee_debut_train,
        journee_fin=journee_fin_train if cfg.journee_fin_train is None else cfg.journee_fin_train,
        mode="train",
        version_ia=cfg.version_ia,
        feature_session_id=feature_session_id,
    )
    eval_env = BettingEnv(
        capital_initial=config.DEFAULT_BANKROLL,
        journee_debut=journee_debut_eval if cfg.journee_debut_eval is None else cfg.journee_debut_eval,
        journee_fin=journee_fin_eval if cfg.journee_fin_eval is None else cfg.journee_fin_eval,
        mode="eval",
        version_ia=cfg.version_ia,
        feature_session_id=feature_session_id,
    )
    print("Creation de l'agent PPO...")
    model = create_ppo_agent(
        train_env,
        PPOConfig(learning_rate=cfg.learning_rate, tensorboard_log=config.ZEUS_LOGS_DIR, verbose=1),
    )
    print("Configuration des callbacks...")
    callbacks = create_callbacks(
        eval_env=eval_env,
        config=CallbackConfig(checkpoint_freq=cfg.checkpoint_freq, eval_freq=cfg.eval_freq),
    )
    print(f"\nDebut de l'entrainement ({cfg.n_timesteps:,} timesteps)...")
    print("Suivez la progression avec: tensorboard --logdir ./logs/zeus/")
    print("-" * 60)
    model.learn(
        total_timesteps=cfg.n_timesteps,
        callback=callbacks,
        progress_bar=True,
    )
    os.makedirs("./models/zeus/", exist_ok=True)
    final_model_path = f"./models/zeus/zeus_final_{cfg.version_ia}"
    model.save(final_model_path)
    print("\n" + "=" * 60)
    print("Entrainement termine!")
    print(f"Modele sauvegarde: {final_model_path}.zip")
    print("Meilleur modele: ./models/zeus/best/best_model.zip")
    print("=" * 60)
    train_env.close()
    eval_env.close()
    return model
