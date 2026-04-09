"""
Pilier 6 — PPO plus puissant pour ZEUS v2.

Hyperparamètres optimisés pour les matchs virtuels Bet261 :
- Épisodes COURTS (37 matchs max par épisode)
- Patterns RÉPÉTITIFS (même RNG, biais stables)
- Horizon COURT → gamma réduit (0.95 vs 0.99)
- Plus d'exploration initiale → ent_coef élevé (0.05)
- Réseau plus profond → [256, 256, 128]
"""
import os
from dataclasses import dataclass
from typing import Optional

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback


@dataclass(frozen=True)
class PPOConfig:
    # --- Architecture réseau ---
    # v1: [128, 128] | v2: [256, 256, 128] — Plus de capacité pour les patterns subtils
    net_arch: tuple = (256, 256, 128)

    # --- Taux d'apprentissage ---
    # Réduit (1e-4 vs 3e-4) pour stabilité avec le réseau plus profond
    learning_rate: float = 1e-4

    # --- Collecte de données ---
    # Réduit (1024 vs 2048) : adapté aux épisodes courts de 37 steps max
    n_steps: int = 1024

    batch_size: int = 64
    n_epochs: int = 10

    # --- Facteur de discount ---
    # Réduit (0.95 vs 0.99) : horizon court, le futur est moins important
    gamma: float = 0.95

    # --- GAE lambda ---
    # Réduit (0.90 vs 0.95) : réduit la variance sur épisodes courts
    gae_lambda: float = 0.90

    clip_range: float = 0.2

    # --- Exploration ---
    # Augmenté (0.05 vs 0.01) : plus d'exploration initiale pour trouver les patterns EV+
    ent_coef: float = 0.05

    vf_coef: float = 0.5
    max_grad_norm: float = 0.5

    tensorboard_log: Optional[str] = "./logs/zeus/"
    verbose: int = 1


@dataclass(frozen=True)
class CallbackConfig:
    checkpoint_freq: int = 50_000
    eval_freq: int = 10_000
    checkpoint_dir: str = "./models/zeus/checkpoints/"
    best_model_dir: str = "./models/zeus/best/"
    log_dir: str = "./logs/zeus/eval/"


def create_ppo_agent(env, config: Optional[PPOConfig] = None):
    """Crée un agent PPO ZEUS v2 avec le réseau [256, 256, 128]."""
    cfg = config or PPOConfig()

    # Architecture en liste de dicts pour stable-baselines3
    net_arch = [dict(pi=list(cfg.net_arch), vf=list(cfg.net_arch))]
    policy_kwargs = {"net_arch": net_arch}

    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=cfg.learning_rate,
        n_steps=cfg.n_steps,
        batch_size=cfg.batch_size,
        n_epochs=cfg.n_epochs,
        gamma=cfg.gamma,
        gae_lambda=cfg.gae_lambda,
        clip_range=cfg.clip_range,
        clip_range_vf=None,
        ent_coef=cfg.ent_coef,
        vf_coef=cfg.vf_coef,
        max_grad_norm=cfg.max_grad_norm,
        verbose=cfg.verbose,
        tensorboard_log=cfg.tensorboard_log,
        policy_kwargs=policy_kwargs,
        seed=None,
    )
    return model


def load_ppo_agent(model_path: str, env=None):
    """Charge un modèle PPO existant."""
    model = PPO.load(model_path, env=env)
    return model


def create_callbacks(eval_env, config: Optional[CallbackConfig] = None):
    """Crée les callbacks de sauvegarde et d'évaluation."""
    cfg = config or CallbackConfig()
    os.makedirs(cfg.checkpoint_dir, exist_ok=True)
    os.makedirs(cfg.best_model_dir, exist_ok=True)
    os.makedirs(cfg.log_dir, exist_ok=True)

    checkpoint_callback = CheckpointCallback(
        save_freq=cfg.checkpoint_freq,
        save_path=cfg.checkpoint_dir,
        name_prefix="zeus_v2_checkpoint",
    )
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=cfg.best_model_dir,
        log_path=cfg.log_dir,
        eval_freq=cfg.eval_freq,
        deterministic=True,
        render=False,
        verbose=1,
    )
    return [checkpoint_callback, eval_callback]
