"""
Configuration et création de l'agent PPO pour ZEUS.
"""

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
from stable_baselines3.common.vec_env import DummyVecEnv
from typing import Optional
import os


def create_ppo_agent(
    env,
    learning_rate: float = 3e-4,
    n_steps: int = 2048,
    batch_size: int = 64,
    n_epochs: int = 10,
    gamma: float = 0.99,
    gae_lambda: float = 0.95,
    clip_range: float = 0.2,
    ent_coef: float = 0.01,
    vf_coef: float = 0.5,
    max_grad_norm: float = 0.5,
    tensorboard_log: Optional[str] = "./logs/zeus/",
    verbose: int = 1
):
    """
    Crée un agent PPO optimisé pour le betting.
    
    Args:
        env: Environnement Gymnasium (ou VecEnv)
        learning_rate: Taux d'apprentissage
        n_steps: Nombre de steps avant chaque update
        batch_size: Taille des mini-batches
        n_epochs: Nombre d'epochs par update
        gamma: Facteur de discount
        gae_lambda: Lambda pour GAE
        clip_range: Clip PPO
        ent_coef: Coefficient d'entropie (faible = plus d'exploitation)
        vf_coef: Coefficient de la value function
        max_grad_norm: Gradient clipping
        tensorboard_log: Dossier pour logs tensorboard
        verbose: Niveau de verbosité
        
    Returns:
        Modèle PPO configuré
    """
    # Configuration du réseau de neurones
    policy_kwargs = {
        "net_arch": [
            dict(pi=[128, 128], vf=[128, 128])  # 2 couches de 128 neurones
        ]
    }
    
    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=learning_rate,
        n_steps=n_steps,
        batch_size=batch_size,
        n_epochs=n_epochs,
        gamma=gamma,
        gae_lambda=gae_lambda,
        clip_range=clip_range,
        clip_range_vf=None,
        ent_coef=ent_coef,
        vf_coef=vf_coef,
        max_grad_norm=max_grad_norm,
        verbose=verbose,
        tensorboard_log=tensorboard_log,
        policy_kwargs=policy_kwargs,
        seed=None
    )
    
    return model


def load_ppo_agent(model_path: str, env=None):
    """
    Charge un agent PPO sauvegardé.
    
    Args:
        model_path: Chemin vers le modèle .zip
        env: Environnement (optionnel, pour continuer l'entraînement)
        
    Returns:
        Modèle PPO chargé
    """
    model = PPO.load(model_path, env=env)
    return model


def create_callbacks(
    eval_env,
    checkpoint_freq: int = 50000,
    eval_freq: int = 10000,
    checkpoint_dir: str = "./models/zeus/checkpoints/",
    best_model_dir: str = "./models/zeus/best/",
    log_dir: str = "./logs/zeus/eval/"
):
    """
    Crée les callbacks pour l'entraînement.
    
    Args:
        eval_env: Environnement d'évaluation
        checkpoint_freq: Fréquence de sauvegarde (en steps)
        eval_freq: Fréquence d'évaluation (en steps)
        checkpoint_dir: Dossier pour checkpoints
        best_model_dir: Dossier pour meilleur modèle
        log_dir: Dossier pour logs d'évaluation
        
    Returns:
        Liste de callbacks
    """
    # Créer les dossiers si nécessaire
    os.makedirs(checkpoint_dir, exist_ok=True)
    os.makedirs(best_model_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    
    # Callback de checkpoint
    checkpoint_callback = CheckpointCallback(
        save_freq=checkpoint_freq,
        save_path=checkpoint_dir,
        name_prefix="zeus_checkpoint"
    )
    
    # Callback d'évaluation
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=best_model_dir,
        log_path=log_dir,
        eval_freq=eval_freq,
        deterministic=True,
        render=False,
        verbose=1
    )
    
    return [checkpoint_callback, eval_callback]
