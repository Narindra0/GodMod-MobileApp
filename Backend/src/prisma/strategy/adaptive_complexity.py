"""
PRISMA Adaptive Complexity Module
Gestion de la complexité adaptative des modèles selon la position dans la session.
Logique : plus on avance dans la session, plus le modèle doit être simple et stable.
"""

import logging
import math
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# Définition des phases de session
SESSION_PHASES = {
    'early': {      # Journées 1-8 : Exploration, forte variance
        'day_range': (1, 8),
        'complexity': 'high',
        'description': 'Phase exploratoire - modèles complexes pour capturer les signaux faibles'
    },
    'mid': {         # Journées 9-16 : Stabilisation, patterns émergents
        'day_range': (9, 16),
        'complexity': 'medium',
        'description': 'Phase de stabilisation - équilibre complexité/stabilité'
    },
    'late': {        # Journées 17-25 : Consolidation, prédictibilité forte
        'day_range': (17, 25),
        'complexity': 'low',
        'description': 'Phase finale - modèles simples et robustes'
    },
    'end': {         # Journées 26+ : Fin de session, forte pression
        'day_range': (26, 38),
        'complexity': 'minimal',
        'description': 'Phase terminale - modèles minimalistes ultra-stables'
    }
}

# Configurations XGBoost par complexité
XGBOOST_CONFIGS = {
    'high': {
        'n_estimators': 300,
        'max_depth': 7,
        'learning_rate': 0.03,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'min_child_weight': 1,
        'gamma': 0.1,
        'reg_alpha': 0.01,
        'reg_lambda': 1.0,
        'description': 'Complexe - capture signaux faibles'
    },
    'medium': {
        'n_estimators': 250,
        'max_depth': 6,
        'learning_rate': 0.05,
        'subsample': 0.85,
        'colsample_bytree': 0.85,
        'min_child_weight': 2,
        'gamma': 0.2,
        'reg_alpha': 0.05,
        'reg_lambda': 1.5,
        'description': 'Équilibré - robustesse et performance'
    },
    'low': {
        'n_estimators': 200,
        'max_depth': 5,
        'learning_rate': 0.07,
        'subsample': 0.9,
        'colsample_bytree': 0.9,
        'min_child_weight': 3,
        'gamma': 0.3,
        'reg_alpha': 0.1,
        'reg_lambda': 2.0,
        'description': 'Simple - stabilité maximale'
    },
    'minimal': {
        'n_estimators': 150,
        'max_depth': 4,
        'learning_rate': 0.1,
        'subsample': 0.95,
        'colsample_bytree': 0.95,
        'min_child_weight': 5,
        'gamma': 0.5,
        'reg_alpha': 0.2,
        'reg_lambda': 3.0,
        'description': 'Minimaliste - ultra-stable'
    }
}

# Configurations CatBoost par complexité
CATBOOST_CONFIGS = {
    'high': {
        'iterations': 300,
        'depth': 8,
        'learning_rate': 0.03,
        'l2_leaf_reg': 2,
        'border_count': 128,
        'bagging_temperature': 0.8,
        'random_strength': 1.0,
        'description': 'Complexe - capture patterns complexes'
    },
    'medium': {
        'iterations': 250,
        'depth': 7,
        'learning_rate': 0.05,
        'l2_leaf_reg': 3,
        'border_count': 100,
        'bagging_temperature': 0.6,
        'random_strength': 0.8,
        'description': 'Équilibré - performance stable'
    },
    'low': {
        'iterations': 200,
        'depth': 6,
        'learning_rate': 0.07,
        'l2_leaf_reg': 4,
        'border_count': 80,
        'bagging_temperature': 0.4,
        'random_strength': 0.5,
        'description': 'Simple - robustesse accrue'
    },
    'minimal': {
        'iterations': 150,
        'depth': 5,
        'learning_rate': 0.1,
        'l2_leaf_reg': 5,
        'border_count': 64,
        'bagging_temperature': 0.2,
        'random_strength': 0.3,
        'description': 'Minimaliste - stabilité maximale'
    }
}

def get_session_phase(current_day: int) -> str:
    """
    Détermine la phase actuelle de la session selon la journée.
    
    Args:
        current_day: Journée actuelle (1-38)
        
    Returns:
        str: Phase de la session ('early', 'mid', 'late', 'end')
    """
    for phase_name, phase_info in SESSION_PHASES.items():
        start_day, end_day = phase_info['day_range']
        if start_day <= current_day <= end_day:
            logger.info(f"[ADAPTIVE] Journée {current_day} -> Phase {phase_name} ({phase_info['description']})")
            return phase_name
    
    # Par défaut, phase minimale pour journées très avancées
    logger.warning(f"[ADAPTIVE] Journée {current_day} hors limites -> Phase minimale par défaut")
    return 'minimal'

def get_xgboost_config(current_day: int) -> Dict:
    """
    Retourne la configuration XGBoost adaptée à la journée actuelle.
    
    Args:
        current_day: Journée actuelle
        
    Returns:
        Dict: Configuration XGBoost optimisée
    """
    phase = get_session_phase(current_day)
    # Récupérer le niveau de complexité associé à la phase
    config_phase = SESSION_PHASES[phase]['complexity']
    config = XGBOOST_CONFIGS[config_phase].copy()
    config['phase'] = phase
    config['current_day'] = current_day
    
    logger.info(f"[ADAPTIVE] Config XGBoost {phase} (niveau {config_phase}): {config['description']}")
    return config

def get_catboost_config(current_day: int) -> Dict:
    """
    Retourne la configuration CatBoost adaptée à la journée actuelle.
    
    Args:
        current_day: Journée actuelle
        
    Returns:
        Dict: Configuration CatBoost optimisée
    """
    phase = get_session_phase(current_day)
    # Récupérer le niveau de complexité associé à la phase
    config_phase = SESSION_PHASES[phase]['complexity']
    config = CATBOOST_CONFIGS[config_phase].copy()
    config['phase'] = phase
    config['current_day'] = current_day
    
    logger.info(f"[ADAPTIVE] Config CatBoost {phase} (niveau {config_phase}): {config['description']}")
    return config

def should_retrain_by_day(current_day: int, last_training_day: int) -> bool:
    """
    Détermine si un réentraînement est nécessaire selon les journées.
    
    Args:
        current_day: Journée actuelle
        last_training_day: Dernière journée d'entraînement
        
    Returns:
        bool: True si réentraînement nécessaire
    """
    if last_training_day == 0:
        logger.info("[ADAPTIVE] Premier entraînement - requis")
        return True
    
    # Réentraînement toutes les 5 journées
    day_diff = current_day - last_training_day
    if day_diff >= 5:
        logger.info(f"[ADAPTIVE] Réentraînement requis: {current_day} - {last_training_day} = {day_diff} journées (>=5)")
        return True
    
    logger.info(f"[ADAPTIVE] Pas de réentraînement: {current_day} - {last_training_day} = {day_diff} journées (<5)")
    return False

def get_training_context(conn, session_id: int) -> Dict:
    """
    Récupère le contexte d'entraînement complet.
    
    Args:
        conn: Connexion DB
        session_id: ID de la session
        
    Returns:
        Dict: Contexte avec journée actuelle, phase, configs
    """
    cursor = conn.cursor()
    
    # Récupérer la journée actuelle
    cursor.execute("""
        SELECT current_day FROM sessions 
        WHERE id = %s
    """, (session_id,))
    
    result = cursor.fetchone()
    if not result:
        logger.error(f"[ADAPTIVE] Session {session_id} non trouvée")
        return {}
    
    current_day = result['current_day'] or 1
    
    # Construire le contexte
    try:
        phase = get_session_phase(current_day)
        context = {
            'session_id': session_id,
            'current_day': current_day,
            'phase': phase,
            'xgboost_config': get_xgboost_config(current_day),
            'catboost_config': get_catboost_config(current_day),
            'phase_info': SESSION_PHASES[phase]
        }
        
        logger.info(f"[ADAPTIVE] Contexte session {session_id}: J{current_day} Phase {context['phase']}")
        return context
    except Exception as e:
        logger.error(f"[ADAPTIVE] Erreur construction contexte: {e}")
        # Retourner un contexte minimal
        return {
            'session_id': session_id,
            'current_day': current_day,
            'phase': 'mid',
            'xgboost_config': {},
            'catboost_config': {},
            'phase_info': {}
        }

def log_complexity_summary(context: Dict):
    """
    Affiche un résumé de la configuration de complexité.
    
    Args:
        context: Contexte d'entraînement
    """
    phase = context['phase']
    current_day = context['current_day']
    
    logger.info("=" * 60)
    logger.info(f"[ADAPTIVE] RÉSUMÉ COMPLEXITÉ - J{current_day} Phase {phase.upper()}")
    logger.info(f"Description: {context['phase_info']['description']}")
    logger.info(f"XGBoost: {context['xgboost_config']['description']}")
    logger.info(f"  - n_estimators: {context['xgboost_config']['n_estimators']}")
    logger.info(f"  - max_depth: {context['xgboost_config']['max_depth']}")
    logger.info(f"  - learning_rate: {context['xgboost_config']['learning_rate']}")
    logger.info(f"CatBoost: {context['catboost_config']['description']}")
    logger.info(f"  - iterations: {context['catboost_config']['iterations']}")
    logger.info(f"  - depth: {context['catboost_config']['depth']}")
    logger.info(f"  - learning_rate: {context['catboost_config']['learning_rate']}")
    logger.info("=" * 60)
