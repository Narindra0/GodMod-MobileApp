"""
Module d'inférence pour ZEUS en production.
Gère la conversion des données de match en actions concrètes.
"""

import os
import sqlite3
import numpy as np
from typing import Dict, Optional, Tuple
from stable_baselines3 import PPO

from ..environment.observation import construire_observation
from ..environment.betting_env import ACTION_SPACE_CONFIG
from ...core import config

# Singleton pour le modèle
_ZEUS_MODEL = None

def get_zeus_model(model_path: str = None) -> Optional[PPO]:
    """Charge et retourne le modèle ZEUS (Singleton)."""
    global _ZEUS_MODEL
    if _ZEUS_MODEL is None:
        path = model_path or config.ZEUS_MODEL_PATH
        if os.path.exists(path):
            try:
                _ZEUS_MODEL = PPO.load(path)
            except Exception as e:
                print(f"❌ Erreur chargement ZEUS : {e}")
                return None
        else:
            return None
    return _ZEUS_MODEL

def obtenir_action_details(action_id: int) -> Dict:
    """Traduit un Action ID en détails lisibles (type, pourcentage)."""
    return ACTION_SPACE_CONFIG.get(action_id, {'type': 'Aucun', 'pourcentage': 0.0})

def predire_pari_zeus(
    model: PPO,
    match_data: Dict,
    conn: sqlite3.Connection
) -> Tuple[int, Dict]:
    """
    Génère une prédiction ZEUS pour un match donné.
    
    Returns:
        Tuple (action_id, action_details)
    """
    # 1. Construire l'observation
    obs = construire_observation(
        match_data['equipe_dom_id'],
        match_data['equipe_ext_id'],
        match_data['journee'],
        match_data['cote_1'],
        match_data['cote_x'],
        match_data['cote_2'],
        conn
    )
    
    # 2. Inférence (Action déterministe en production)
    action, _ = model.predict(obs, deterministic=True)
    action_id = int(action)
    
    # 3. Détails
    details = obtenir_action_details(action_id)
    
    return action_id, details

def formater_decision_zeus(action_details: Dict) -> str:
    """Formate l'action pour l'affichage console."""
    pari_type = action_details['type']
    pourcentage = action_details['pourcentage']
    
    if pari_type == 'Aucun':
        return "[yellow]Abstention[/]"
    
    label = "Prudent" if pourcentage < 0.08 else "Conviction"
    color = "cyan" if label == "Prudent" else "bold cyan"
    
    return f"[{color}]{pari_type} ({label})[/]"
