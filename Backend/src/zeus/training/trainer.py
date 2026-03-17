import os
import sqlite3
from typing import Optional
from ..environment.betting_env import BettingEnv
from ..models.ppo_agent import create_ppo_agent, create_callbacks
from ...core import config


def _select_completed_training_session(db_path: str) -> Optional[int]:
    """
    Sélectionne une session dont les matches couvrent au moins les journées 1 à 37 (incluses).
    On ne considère que ces sessions "complètes" pour entraîner ZEUS.
    """
    conn = sqlite3.connect(db_path)
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
    conn.close()
    return row[0] if row else None


def train_zeus_agent(
    db_path: str = None,
    n_timesteps: int = 1_000_000,
    checkpoint_freq: int = 50_000,
    eval_freq: int = 10_000,
    learning_rate: float = 3e-4,
    version_ia: str = "v1.0",
    journee_debut_train: Optional[int] = None,
    journee_fin_train: Optional[int] = None,
    journee_debut_eval: Optional[int] = None,
    journee_fin_eval: Optional[int] = None
):
    print("=" * 60)
    print("🏛️  ZEUS - Entraînement de l'agent RL")
    print("=" * 60)
    current_db_path = db_path or config.DB_NAME

    # On sélectionne une session "complète" (jours 1 à 37 terminés) pour l'entraînement.
    feature_session_id = _select_completed_training_session(current_db_path)
    if feature_session_id is None:
        raise ValueError(
            "Aucune session complète trouvée pour l'entraînement ZEUS.\n"
            "Assure-toi d'avoir au moins une session avec des matches TERMINE "
            "pour toutes les journées 1 à 37."
        )
    print(
        f"🔗 Utilisation de la session {feature_session_id} "
        "pour les données de matches/classement (session complète 1-37)."
    )
    # Détermination automatique des plages de journées si non précisées (Mode Flex).
    if journee_debut_train is None:
        conn = sqlite3.connect(current_db_path)
        cursor = conn.cursor()
        # IMPORTANT : on ne considère que les matches de la session sélectionnée.
        cursor.execute(
            "SELECT DISTINCT journee FROM matches "
            "WHERE status = 'TERMINE' AND session_id = ? "
            "ORDER BY journee",
            (feature_session_id,),
        )
        all_journees = [row[0] for row in cursor.fetchall()]

        if len(all_journees) < 10:
            conn.close()
            raise ValueError(
                f"Pas assez de données dans {current_db_path}. "
                f"Trouvé {len(all_journees)} journées, besoin d'au moins 10."
            )

        split_idx = int(len(all_journees) * 0.8)
        journee_debut_train = all_journees[0]
        journee_fin_train = all_journees[split_idx - 1]
        journee_debut_eval = all_journees[split_idx]
        journee_fin_eval = all_journees[-1]

        # Stats basiques sur la distribution des données (nombre de matches).
        def count_matches(j_start: int, j_end: int) -> int:
            cursor.execute(
                "SELECT COUNT(*) FROM matches "
                "WHERE status = 'TERMINE' AND journee BETWEEN ? AND ?",
                (j_start, j_end),
            )
            return cursor.fetchone()[0]

        n_matches_train = count_matches(journee_debut_train, journee_fin_train)
        n_matches_eval = count_matches(journee_debut_eval, journee_fin_eval)
        conn.close()

        print(f"📊 Mode Flex: {len(all_journees)} journées TERMINE dans la base")
        print(
            f"📊 Train: Journées {journee_debut_train} à {journee_fin_train} "
            f"({n_matches_train} matches)"
        )
        print(
            f"📊 Eval:  Journées {journee_debut_eval} à {journee_fin_eval} "
            f"({n_matches_eval} matches)"
        )
    else:
        print(
            f"📊 Plages manuelles: "
            f"Train J{journee_debut_train}-{journee_fin_train}, "
            f"Eval J{journee_debut_eval}-{journee_fin_eval}"
        )
    print("\n🔧 Création des environnements...")
    train_env = BettingEnv(
        db_path=current_db_path,
        capital_initial=20000,
        journee_debut=journee_debut_train,
        journee_fin=journee_fin_train,
        mode='train',
        version_ia=version_ia,
        feature_session_id=feature_session_id
    )
    eval_env = BettingEnv(
        db_path=current_db_path,
        capital_initial=20000,
        journee_debut=journee_debut_eval,
        journee_fin=journee_fin_eval,
        mode='eval',
        version_ia=version_ia,
        feature_session_id=feature_session_id
    )
    print("🧠 Création de l'agent PPO...")
    model = create_ppo_agent(
        train_env,
        learning_rate=learning_rate,
        tensorboard_log=config.ZEUS_LOGS_DIR,
        verbose=1
    )
    print("📋 Configuration des callbacks...")
    callbacks = create_callbacks(
        eval_env=eval_env,
        checkpoint_freq=checkpoint_freq,
        eval_freq=eval_freq
    )
    print(f"\n🚀 Début de l'entraînement ({n_timesteps:,} timesteps)...")
    print("📊 Suivez la progression avec: tensorboard --logdir ./logs/zeus/")
    print("-" * 60)
    model.learn(
        total_timesteps=n_timesteps,
        callback=callbacks,
        progress_bar=True
    )
    os.makedirs("./models/zeus/", exist_ok=True)
    final_model_path = f"./models/zeus/zeus_final_{version_ia}"
    model.save(final_model_path)
    print("\n" + "=" * 60)
    print(f"✅ Entraînement terminé!")
    print(f"📦 Modèle sauvegardé: {final_model_path}.zip")
    print(f"🏆 Meilleur modèle: ./models/zeus/best/best_model.zip")
    print("=" * 60)
    train_env.close()
    eval_env.close()
    return model
