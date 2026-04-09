"""
PRISMA Training Triggers Module
Gestion des triggers de réentraînement avancés (sessions + journées + performance).
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

class TrainingTrigger:
    """Gestionnaire des triggers de réentraînement."""
    
    def __init__(self, conn):
        self.conn = conn
        
    def get_last_training_info(self, model_name: str) -> Dict:
        """
        Récupère les informations du dernier entraînement.
        
        Args:
            model_name: Nom du modèle ('xgboost' ou 'catboost')
            
        Returns:
            Dict: Infos du dernier entraînement
        """
        try:
            # Charger les métadonnées du modèle
            from prisma import xgboost_model, catboost_model, lightgbm_model
            
            if model_name == 'xgboost':
                metadata = xgboost_model.get_model_info()
            elif model_name == 'catboost':
                metadata = catboost_model.get_model_info()
            elif model_name == 'lightgbm':
                metadata = lightgbm_model.get_model_info()
            else:
                logger.error(f"[TRIGGERS] Modèle inconnu: {model_name}")
                return {}
            
            if not metadata:
                return {'last_training_session': 0, 'last_training_day': 0}
            
            # Extraire les informations
            info = {
                'last_training_session': metadata.get('last_training_session', 0),
                'last_training_day': metadata.get('last_training_day', 0),
                'trained_at': metadata.get('trained_at'),
                'training_method': metadata.get('training_method', 'unknown'),
                'cv_accuracy': metadata.get('cv_accuracy', 0.0)
            }
            
            logger.info(f"[TRIGGERS] Dernier entraînement {model_name}: Session {info['last_training_session']}, J{info['last_training_day']}")
            return info
            
        except Exception as e:
            logger.error(f"[TRIGGERS] Erreur lecture métadonnées {model_name}: {e}")
            return {'last_training_session': 0, 'last_training_day': 0}
    
    def check_session_trigger(self, current_session_id: int, last_session_id: int) -> Tuple[bool, str]:
        """
        Vérifie le trigger basé sur les sessions.
        
        Args:
            current_session_id: Session actuelle
            last_session_id: Dernière session d'entraînement
            
        Returns:
            Tuple[bool, str]: (trigger_activated, reason)
        """
        if current_session_id > last_session_id:
            reason = f"Nouvelle session détectée: {current_session_id} > {last_session_id}"
            logger.info(f"[TRIGGERS] ✅ Trigger session: {reason}")
            return True, reason
        
        return False, ""
    
    def check_day_trigger(self, current_day: int, last_day: int) -> Tuple[bool, str]:
        """
        Vérifie le trigger basé sur les journées (toutes les 5 journées).
        
        Args:
            current_day: Journée actuelle
            last_day: Dernière journée d'entraînement
            
        Returns:
            Tuple[bool, str]: (trigger_activated, reason)
        """
        if last_day == 0:
            reason = f"Premier entraînement (jour {current_day})"
            logger.info(f"[TRIGGERS] ✅ Trigger initial: {reason}")
            return True, reason
        
        day_diff = current_day - last_day
        if day_diff >= 5:
            reason = f"Écart de {day_diff} journées (>=5): J{current_day} - J{last_day}"
            logger.info(f"[TRIGGERS] ✅ Trigger journée: {reason}")
            return True, reason
        
        return False, ""
    
    def check_performance_trigger(self, model_name: str, current_accuracy: float, last_accuracy: float) -> Tuple[bool, str]:
        """
        Vérifie le trigger basé sur la performance (baisse significative).
        
        Args:
            model_name: Nom du modèle
            current_accuracy: Accuracy CV actuelle
            last_accuracy: Dernière accuracy enregistrée
            
        Returns:
            Tuple[bool, str]: (trigger_activated, reason)
        """
        if last_accuracy == 0:
            return False, ""
        
        accuracy_drop = last_accuracy - current_accuracy
        drop_threshold = 0.05  # 5% de baisse
        
        if accuracy_drop > drop_threshold:
            reason = f"Baisse performance {model_name}: {accuracy_drop:.3f} > {drop_threshold} ({last_accuracy:.3f} -> {current_accuracy:.3f})"
            logger.info(f"[TRIGGERS] ✅ Trigger performance: {reason}")
            return True, reason
        
        return False, ""
    
    def check_data_volume_trigger(self, current_session_id: int, min_new_matches: int = 50) -> Tuple[bool, str]:
        """
        Vérifie le trigger basé sur le volume de nouvelles données.
        
        Args:
            current_session_id: Session actuelle
            min_new_matches: Nombre minimum de nouveaux matchs
            
        Returns:
            Tuple[bool, str]: (trigger_activated, reason)
        """
        try:
            # Compter les matchs depuis le dernier entraînement
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as new_matches 
                FROM matches m
                WHERE m.session_id = %s
                AND m.score_dom IS NOT NULL 
                AND m.score_ext IS NOT NULL
            """, (current_session_id,))
            
            result = cursor.fetchone()
            cursor.close()
            new_matches = result['new_matches'] if result else 0
            
            if new_matches >= min_new_matches:
                reason = f"Volume données suffisant: {new_matches} nouveaux matchs (>= {min_new_matches})"
                logger.info(f"[TRIGGERS] ✅ Trigger volume: {reason}")
                return True, reason
            
            return False, ""
            
        except Exception as e:
            logger.error(f"[TRIGGERS] Erreur vérification volume: {e}")
            return False, ""
    
    def check_feature_count_trigger(self, model_name: str) -> Tuple[bool, str]:
        """
        Vérifie si le modèle sur disque a un nombre de features cohérent.
        Force le réentraînement si on détecte un ancien modèle (ex: 31 features).
        """
        try:
            from prisma import xgboost_model, catboost_model, lightgbm_model
            
            if model_name == 'xgboost':
                info = xgboost_model.get_model_info()
                expected = 57
            elif model_name == 'catboost':
                info = catboost_model.get_model_info()
                expected = 59
            elif model_name == 'lightgbm':
                info = lightgbm_model.get_model_info()
                expected = 57
            else:
                return False, ""
                
            actual_count = info.get('features_count', 0)
            
            # Si le modèle existe mais n'a pas le bon format
            if actual_count > 0 and actual_count != expected:
                reason = f"Structure obsolète: {actual_count} features (attendu: {expected}). Réentraînement forcé."
                logger.warning(f"[TRIGGERS] ⚠️ {model_name.upper()} {reason}")
                return True, reason
                
            return False, ""
        except Exception as e:
            logger.error(f"[TRIGGERS] Erreur check structure {model_name}: {e}")
            return False, ""

    def evaluate_all_triggers(self, model_name: str, current_session_id: int, current_day: int) -> Dict:
        """
        Évalue tous les triggers et décide du réentraînement.
        
        Args:
            model_name: Nom du modèle
            current_session_id: Session actuelle
            current_day: Journée actuelle
            
        Returns:
            Dict: Décision avec raisons
        """
        # Récupérer les infos du dernier entraînement
        last_info = self.get_last_training_info(model_name)
        last_session = last_info.get('last_training_session', 0)
        last_day = last_info.get('last_training_day', 0)
        last_accuracy = last_info.get('cv_accuracy', 0.0)
        
        # Évaluer chaque trigger
        triggers = []
        
        # Trigger session
        session_triggered, session_reason = self.check_session_trigger(current_session_id, last_session)
        if session_triggered:
            triggers.append({'type': 'session', 'reason': session_reason, 'priority': 'high'})
        
        # Trigger journée
        day_triggered, day_reason = self.check_day_trigger(current_day, last_day)
        if day_triggered:
            triggers.append({'type': 'day', 'reason': day_reason, 'priority': 'medium'})
        
        # Trigger performance (si accuracy disponible)
        if last_accuracy > 0:
            # Simuler une accuracy actuelle (en pratique, viendrait d'une évaluation récente)
            current_accuracy = last_accuracy * 0.98  # Simulation de 2% de baisse
            perf_triggered, perf_reason = self.check_performance_trigger(model_name, current_accuracy, last_accuracy)
            if perf_triggered:
                triggers.append({'type': 'performance', 'reason': perf_reason, 'priority': 'high'})
        
        # Trigger volume données
        volume_triggered, volume_reason = self.check_data_volume_trigger(current_session_id)
        if volume_triggered:
            triggers.append({'type': 'volume', 'reason': volume_reason, 'priority': 'low'})
        
        # Décision finale
        should_train = len(triggers) > 0
        primary_reason = triggers[0]['reason'] if triggers else "Aucun trigger activé"
        
        decision = {
            'should_train': should_train,
            'triggers': triggers,
            'primary_reason': primary_reason,
            'context': {
                'model_name': model_name,
                'current_session': current_session_id,
                'current_day': current_day,
                'last_session': last_session,
                'last_day': last_day,
                'last_accuracy': last_accuracy
            }
        }
        
        if should_train:
            logger.info(f"[TRIGGERS] 🚀 DÉCISION RÉENTRAÎNEMENT {model_name.upper()}: {primary_reason}")
            for trigger in triggers:
                logger.info(f"  - {trigger['type'].upper()}: {trigger['reason']}")
        else:
            logger.info(f"[TRIGGERS] ⏸️ PAS DE RÉENTRAÎNEMENT {model_name.upper()}: {primary_reason}")
        
        return decision
    
    def log_training_decision(self, decision: Dict):
        """
        Enregistre la décision d'entraînement dans les logs.
        
        Args:
            decision: Décision d'entraînement
        """
        model_name = decision['context']['model_name'].upper()
        should_train = decision['should_train']
        primary_reason = decision['primary_reason']
        
        logger.info("=" * 80)
        logger.info(f"[TRIGGERS] DÉCISION ENTRAÎNEMENT {model_name}")
        logger.info(f"Session: {decision['context']['current_session']} (dernière: {decision['context']['last_session']})")
        logger.info(f"Journée: {decision['context']['current_day']} (dernière: {decision['context']['last_day']})")
        logger.info(f"Décision: {'✅ ENTRAÎNER' if should_train else '⏸️ SAUTER'}")
        logger.info(f"Raison: {primary_reason}")
        
        if decision['triggers']:
            logger.info("Triggers activés:")
            for trigger in decision['triggers']:
                logger.info(f"  - {trigger['type'].upper()} ({trigger['priority']}): {trigger['reason']}")
        
        logger.info("=" * 80)

def should_retrain_models(conn, current_session_id: int, current_day: int) -> Dict[str, Dict]:
    """
    Évalue les triggers pour tous les modèles.
    
    Args:
        conn: Connexion DB
        current_session_id: Session actuelle
        current_day: Journée actuelle
        
    Returns:
        Dict[str, Dict]: Décisions par modèle
    """
    trigger_manager = TrainingTrigger(conn)
    
    decisions = {
        'xgboost': trigger_manager.evaluate_all_triggers('xgboost', current_session_id, current_day),
        'catboost': trigger_manager.evaluate_all_triggers('catboost', current_session_id, current_day),
        'lightgbm': trigger_manager.evaluate_all_triggers('lightgbm', current_session_id, current_day)
    }
    
    return decisions

def get_training_summary(decisions: Dict[str, Dict]) -> Dict:
    """
    Génère un résumé des décisions d'entraînement.
    
    Args:
        decisions: Décisions par modèle
        
    Returns:
        Dict: Résumé
    """
    summary = {
        'models_to_train': [],
        'models_to_skip': [],
        'total_triggers': 0,
        'high_priority_triggers': 0,
        'timestamp': datetime.now().isoformat()
    }
    
    for model_name, decision in decisions.items():
        if decision['should_train']:
            summary['models_to_train'].append(model_name)
            
            # Compter les triggers par priorité
            for trigger in decision['triggers']:
                summary['total_triggers'] += 1
                if trigger['priority'] == 'high':
                    summary['high_priority_triggers'] += 1
        else:
            summary['models_to_skip'].append(model_name)
    
    return summary
