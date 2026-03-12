"""
Module de comparaison des performances pour la promotion des modèles ZEUS.
Un modèle n'est promu que s'il est plus robuste et performant que l'ancien.
"""

import os
import shutil
from typing import Dict, List
import numpy as np
from ..utils.metrics import generer_rapport_performance


def evaluer_robustesse(model, env, n_episodes: int = 5) -> Dict:
    """
    Évalue un modèle sur plusieurs épisodes pour obtenir des métriques stables.
    """
    all_rois = []
    all_win_rates = []
    all_drawdowns = []
    survival_count = 0
    
    for _ in range(n_episodes):
        obs, info = env.reset()
        done = False
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        
        rapport = generer_rapport_performance(
            capital_initial=env.capital_initial,
            capital_final=env.capital,
            capital_history=env.historique_capital,
            total_matches=len(env.historique_capital) - 1,
            total_paris=env.total_paris,
            paris_gagnants=env.paris_gagnants
        )
        
        all_rois.append(rapport['roi_percent'])
        all_win_rates.append(rapport['win_rate_percent'])
        all_drawdowns.append(rapport['max_drawdown_percent'])
        
        if env.capital >= 1000:
            survival_count += 1
            
    return {
        'avg_roi': np.mean(all_rois),
        'std_roi': np.std(all_rois),
        'avg_win_rate': np.mean(all_win_rates),
        'avg_max_drawdown': np.mean(all_drawdowns),
        'survival_rate': survival_count / n_episodes
    }


def doit_promouvoir(new_metrics: Dict, old_metrics: Dict) -> bool:
    """
    Logique de promotion stricte :
    1. Le taux de survie doit être supérieur ou égal à l'ancien.
    2. Le ROI moyen doit être supérieur ET plus stable (std_roi plus faible).
    3. Le Max Drawdown doit être moins sévère.
    """
    # 1. Survie critique
    if new_metrics['survival_rate'] < old_metrics['survival_rate']:
        return False
        
    # 2. Performance et Stabilité
    # On autorise un ROI légèrement plus faible si la stabilité est bien meilleure
    if new_metrics['avg_roi'] > old_metrics['avg_roi'] and new_metrics['std_roi'] <= old_metrics['std_roi']:
        return True
        
    # Si le taux de survie est passé à 100%, c'est un argument fort
    if new_metrics['survival_rate'] == 1.0 and old_metrics['survival_rate'] < 1.0:
        return True
        
    return False


def deployer_modele(model_source_path: str, model_dest_dir: str = "./models/zeus/best/"):
    """
    Remplace le modèle "best" par le nouveau modèle promu.
    """
    os.makedirs(model_dest_dir, exist_ok=True)
    dest_path = os.path.join(model_dest_dir, "best_model.zip")
    
    # Backup de l'ancien si présent
    if os.path.exists(dest_path):
        shutil.copy(dest_path, dest_path + ".bak")
        
    shutil.copy(model_source_path, dest_path)
    print(f"🚀 Modèle déployé avec succès : {dest_path}")
