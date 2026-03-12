"""
ZEUS - Reinforcement Learning Agent pour paris sportifs optimisés
Utilise PPO (Proximal Policy Optimization) pour maximiser les gains
tout en préservant le capital.
"""

__version__ = "1.0.0"
__author__ = "GODMOD Team"

from .environment.betting_env import BettingEnv
from .models.ppo_agent import create_ppo_agent
from .training.trainer import train_zeus_agent

__all__ = [
    "BettingEnv",
    "create_ppo_agent",
    "train_zeus_agent"
]
