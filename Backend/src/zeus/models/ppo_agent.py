import os
from dataclasses import dataclass
from typing import Optional

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback


@dataclass(frozen=True)
class PPOConfig:
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    tensorboard_log: Optional[str] = "./logs/zeus/"
    verbose: int = 1


@dataclass(frozen=True)
class CallbackConfig:
    checkpoint_freq: int = 50000
    eval_freq: int = 10000
    checkpoint_dir: str = "./models/zeus/checkpoints/"
    best_model_dir: str = "./models/zeus/best/"
    log_dir: str = "./logs/zeus/eval/"


def create_ppo_agent(env, config: Optional[PPOConfig] = None):
    cfg = config or PPOConfig()
    policy_kwargs = {"net_arch": [dict(pi=[128, 128], vf=[128, 128])]}
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
    model = PPO.load(model_path, env=env)
    return model


def create_callbacks(eval_env, config: Optional[CallbackConfig] = None):
    cfg = config or CallbackConfig()
    os.makedirs(cfg.checkpoint_dir, exist_ok=True)
    os.makedirs(cfg.best_model_dir, exist_ok=True)
    os.makedirs(cfg.log_dir, exist_ok=True)
    checkpoint_callback = CheckpointCallback(
        save_freq=cfg.checkpoint_freq, save_path=cfg.checkpoint_dir, name_prefix="zeus_checkpoint"
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
