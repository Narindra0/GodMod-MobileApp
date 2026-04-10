import os
from dataclasses import dataclass
from typing import Optional

from ...core.system import config
from ...core.db.database import get_db_connection
from ..environment.betting_env import BettingEnv
from ..models.ppo_agent import CallbackConfig, PPOConfig, create_callbacks, create_ppo_agent


@dataclass(frozen=True)
class TrainingConfig:
    db_path: str | None = None
    # Augmenté pour Colab GPU T4 (2M vs 1M en v1)
    n_timesteps: int = 2_000_000
    checkpoint_freq: int = 50_000
    eval_freq: int = 10_000
    learning_rate: float = 1e-4         # Réduit vs v1 (3e-4) pour stabilité réseau plus profond
    version_ia: str = "v2.0"
    journee_debut_train: Optional[int] = None
    journee_fin_train: Optional[int] = None
    journee_debut_eval: Optional[int] = None
    journee_fin_eval: Optional[int] = None


def _select_completed_training_session(db_path: str) -> Optional[int]:
    """
    Sélectionne une session avec au moins 37 journées TERMINE.
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
    print("ZEUS v2 — Entraînement de l'agent RL")
    print("  Piliers : RNG Bias | 14 Features | EV+ Reward | Kelly | PPO[256,256,128]")
    print("=" * 60)

    cfg = cfg or TrainingConfig()
    current_db_path = cfg.db_path or config.DB_NAME

    feature_session_id = _select_completed_training_session(current_db_path)
    if feature_session_id is None:
        raise ValueError(
            "Aucune session complète trouvée pour l'entraînement ZEUS.\n"
            "Il faut au moins une session avec 37 journées TERMINE."
        )
    print(f"Session de référence : {feature_session_id} (données matchs/classement)")

    # Détermination automatique des plages de journées
    if cfg.journee_debut_train is None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT journee FROM matches "
                "WHERE status = 'TERMINE' AND session_id = %s "
                "ORDER BY journee",
                (feature_session_id,),
            )
            all_journees = [row["journee"] for row in cursor.fetchall()]

            if len(all_journees) < 10:
                raise ValueError(
                    f"Pas assez de données ({len(all_journees)} journées, min 10)."
                )

            split_idx = int(len(all_journees) * 0.8)
            journee_debut_train = all_journees[0]
            journee_fin_train = all_journees[split_idx - 1]
            journee_debut_eval = all_journees[split_idx]
            journee_fin_eval = all_journees[-1]

            def count_matches(j_start: int, j_end: int) -> int:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM matches "
                    "WHERE status = 'TERMINE' AND journee BETWEEN %s AND %s AND session_id = %s",
                    (j_start, j_end, feature_session_id),
                )
                result = cursor.fetchone()
                return result["count"] if result else 0

            n_train = count_matches(journee_debut_train, journee_fin_train)
            n_eval = count_matches(journee_debut_eval, journee_fin_eval)

            print(f"Mode Flex: {len(all_journees)} journées TERMINE")
            print(f"Train : J{journee_debut_train}→J{journee_fin_train} ({n_train} matchs)")
            print(f"Eval  : J{journee_debut_eval}→J{journee_fin_eval} ({n_eval} matchs)")
    else:
        journee_debut_train = cfg.journee_debut_train
        journee_fin_train = cfg.journee_fin_train
        journee_debut_eval = cfg.journee_debut_eval
        journee_fin_eval = cfg.journee_fin_eval
        print(f"Plages manuelles : Train J{journee_debut_train}-{journee_fin_train} | Eval J{journee_debut_eval}-{journee_fin_eval}")

    print("\nCréation des environnements v2...")
    train_env = BettingEnv(
        capital_initial=config.DEFAULT_BANKROLL,
        journee_debut=journee_debut_train,
        journee_fin=journee_fin_train,
        mode="train",
        version_ia=cfg.version_ia,
        feature_session_id=feature_session_id,
    )
    eval_env = BettingEnv(
        capital_initial=config.DEFAULT_BANKROLL,
        journee_debut=journee_debut_eval,
        journee_fin=journee_fin_eval,
        mode="eval",
        version_ia=cfg.version_ia,
        feature_session_id=feature_session_id,
    )

    print("Création de l'agent PPO v2 [256, 256, 128]...")
    model = create_ppo_agent(
        train_env,
        PPOConfig(
            learning_rate=cfg.learning_rate,
            tensorboard_log=config.ZEUS_LOGS_DIR,
            verbose=1,
        ),
    )

    print("Configuration des callbacks...")
    callbacks = create_callbacks(
        eval_env=eval_env,
        config=CallbackConfig(
            checkpoint_freq=cfg.checkpoint_freq,
            eval_freq=cfg.eval_freq,
        ),
    )

    print(f"\nDébut de l'entraînement ({cfg.n_timesteps:,} timesteps)...")
    print("Suivez la progression : tensorboard --logdir ./logs/zeus/")
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
    print("Entraînement terminé !")
    print(f"Modèle sauvegardé : {final_model_path}.zip")
    print("Meilleur modèle   : ./models/zeus/best/best_model.zip")
    print("=" * 60)

    train_env.close()
    eval_env.close()
    return model
