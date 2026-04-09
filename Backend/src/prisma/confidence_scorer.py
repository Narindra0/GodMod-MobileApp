"""
PRISMA Confidence Scorer Module
Module de scoring de confiance contextuel et filtrage intelligent des prédictions.
Objectif : Identifier les matchs "imprévisibles" et permettre au système de s'abstenir.
"""

import logging
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceScore:
    """Résultat du scoring de confiance."""
    overall_confidence: float
    prediction_reliable: bool
    recommendation: str  # 'BET', 'ABSTAIN', 'CAUTION'
    confidence_components: Dict[str, float]
    explanation: str


class ConfidenceScorer:
    """
    Scorer de confiance contextuel pour les prédictions PRISMA.
    Combine multiple signaux pour évaluer la fiabilité d'une prédiction.
    """
    
    def __init__(self):
        # Seuils de décision
        self.high_confidence_threshold = 0.70
        self.min_confidence_threshold = 0.55
        self.max_divergence_threshold = 0.25
        
        # Poids des composantes
        self.weights = {
            'model_confidence': 0.30,
            'model_agreement': 0.25,
            'market_confidence': 0.20,
            'value_score': 0.15,
            'data_quality': 0.10
        }
    
    def score_prediction(self, ensemble_result: Dict, match_data: Dict) -> ConfidenceScore:
        """
        Calcule le score de confiance global pour une prédiction.
        
        Args:
            ensemble_result: Résultat de predict_ensemble()
            match_data: Données brutes du match
            
        Returns:
            ConfidenceScore avec recommandation
        """
        components = {}
        
        # 1. Confiance du modèle (confidence brute de l'ensemble)
        components['model_confidence'] = self._score_model_confidence(ensemble_result)
        
        # 2. Accord entre modèles
        components['model_agreement'] = self._score_model_agreement(ensemble_result)
        
        # 3. Confiance du marché (basée sur les cotes)
        components['market_confidence'] = self._score_market_confidence(match_data)
        
        # 4. Score de value
        components['value_score'] = self._score_value_opportunity(ensemble_result, match_data)
        
        # 5. Qualité des données
        components['data_quality'] = self._score_data_quality(match_data)
        
        # Calcul du score global pondéré
        overall = sum(
            components[key] * self.weights[key] 
            for key in self.weights.keys()
        )
        
        # Déterminer la recommandation
        reliable, recommendation, explanation = self._make_recommendation(
            overall, components, ensemble_result
        )
        
        return ConfidenceScore(
            overall_confidence=overall,
            prediction_reliable=reliable,
            recommendation=recommendation,
            confidence_components=components,
            explanation=explanation
        )
    
    def _score_model_confidence(self, ensemble_result: Dict) -> float:
        """Évalue la confiance basée sur la probabilité prédite."""
        base_confidence = ensemble_result.get('confidence', 0.5)
        
        # Normaliser entre 0 et 1
        # Une confidence de 0.50 (random) = 0.0
        # Une confidence de 0.85 = 1.0
        normalized = (base_confidence - 0.50) / 0.35
        return np.clip(normalized, 0.0, 1.0)
    
    def _score_model_agreement(self, ensemble_result: Dict) -> float:
        """Évalue l'accord entre les modèles."""
        models = ensemble_result.get('models', {})
        if len(models) < 2:
            return 0.5  # Neutre si un seul modèle
        
        # Vérifier l'accord sur la prédiction
        predictions = [m['prediction'] for m in models.values()]
        all_agree = len(set(predictions)) == 1
        
        if all_agree:
            return 1.0
        
        # Calculer la divergence
        confidences = [m.get('confidence', 0.5) for m in models.values()]
        divergence = max(confidences) - min(confidences)
        
        # Plus la divergence est faible, meilleur est le score
        return np.clip(1.0 - divergence * 2, 0.0, 1.0)
    
    def _score_market_confidence(self, match_data: Dict) -> float:
        """Évalue la confiance basée sur les cotes du marché."""
        cote_1 = match_data.get('cote_1', 2.0)
        cote_x = match_data.get('cote_x', 3.0)
        cote_2 = match_data.get('cote_2', 2.0)
        
        # Calculer l'entropie du marché
        probs = [1.0/c for c in [cote_1, cote_x, cote_2] if c > 0]
        sum_probs = sum(probs)
        
        if sum_probs == 0:
            return 0.5
        
        # Normaliser
        probs = [p / sum_probs for p in probs]
        
        # Entropie de Shannon
        entropy = -sum(p * np.log(p) for p in probs if p > 0)
        max_entropy = np.log(3)
        
        # Plus l'entropie est faible, plus le marché est confiant
        market_confidence = 1.0 - (entropy / max_entropy)
        
        # Pénaliser les cotes très resserrées (suspicion de manipulation)
        min_cote = min(cote_1, cote_x, cote_2)
        if min_cote < 1.15:
            market_confidence *= 0.5
        
        return market_confidence
    
    def _score_value_opportunity(self, ensemble_result: Dict, match_data: Dict) -> float:
        """Évalue l'opportunité de value betting."""
        probs = ensemble_result.get('probabilities', {})
        cote_1 = match_data.get('cote_1', 2.0)
        cote_x = match_data.get('cote_x', 3.0)
        cote_2 = match_data.get('cote_2', 2.0)
        
        if not probs:
            return 0.5
        
        # Trouver la prédiction avec plus haute confiance
        best_outcome = max(probs, key=probs.get)
        best_prob = probs[best_outcome]
        
        # Cote correspondante
        cote_map = {'1': cote_1, 'X': cote_x, '2': cote_2}
        cote = cote_map.get(best_outcome, 2.0)
        
        # Probabilité implicite du marché
        implied_prob = 1.0 / cote
        
        # Value = probabilité prédite - probabilité implicite
        value = best_prob - implied_prob
        
        # Normaliser le score de value
        # value > 0.10 = excellent (1.0)
        # value < 0 = pas de value (0.0)
        if value > 0.10:
            return 1.0
        elif value > 0.05:
            return 0.7
        elif value > 0.0:
            return 0.4
        else:
            return 0.1
    
    def _score_data_quality(self, match_data: Dict) -> float:
        """Évalue la qualité des données disponibles."""
        score = 1.0
        
        # Vérifier les données essentielles
        required_fields = ['pts_dom', 'pts_ext', 'forme_dom', 'forme_ext']
        for field in required_fields:
            if not match_data.get(field):
                score -= 0.15
        
        # Vérifier les cotes
        cotes = [match_data.get('cote_1'), match_data.get('cote_x'), match_data.get('cote_2')]
        if None in cotes or 0 in cotes:
            score -= 0.20
        
        # Vérifier les statistiques buts
        if not match_data.get('bp_dom') or not match_data.get('bc_dom'):
            score -= 0.10
        
        return max(0.0, score)
    
    def _make_recommendation(self, overall: float, components: Dict, 
                            ensemble_result: Dict) -> Tuple[bool, str, str]:
        """
        Prend la décision finale basée sur tous les signaux.
        
        Returns:
            (reliable, recommendation, explanation)
        """
        # Cas évidents
        if overall >= self.high_confidence_threshold:
            return True, 'BET', f"Confiance élevée ({overall:.1%}). Tous les signaux sont positifs."
        
        if overall < self.min_confidence_threshold:
            return False, 'ABSTAIN', f"Confiance insuffisante ({overall:.1%}). Prédiction peu fiable."
        
        # Cas de prudence
        if components['model_agreement'] < 0.3:
            return False, 'ABSTAIN', "Désaccord important entre les modèles. Risque élevé."
        
        if components['data_quality'] < 0.6:
            return False, 'ABSTAIN', "Données incomplètes. Prédiction peu fiable."
        
        if components['value_score'] < 0.2:
            return False, 'ABSTAIN', "Pas d'opportunité de value identifiée."
        
        # Zone de prudence
        return True, 'CAUTION', f"Confiance modérée ({overall:.1%}). Parier avec précaution."
    
    def should_place_bet(self, confidence_score: ConfidenceScore, 
                        min_confidence: float = None) -> Tuple[bool, str]:
        """
        Décide si un pari doit être placé.
        
        Args:
            confidence_score: Résultat du scoring
            min_confidence: Seuil minimum optionnel
            
        Returns:
            (should_bet, reason)
        """
        threshold = min_confidence or self.min_confidence_threshold
        
        if confidence_score.recommendation == 'BET':
            return True, "Recommandation BET"
        
        if confidence_score.recommendation == 'ABSTAIN':
            return False, f"Recommandation ABSTAIN: {confidence_score.explanation}"
        
        if confidence_score.recommendation == 'CAUTION':
            if confidence_score.overall_confidence >= threshold:
                return True, f"CAUTION avec confiance suffisante ({confidence_score.overall_confidence:.1%})"
            else:
                return False, f"CAUTION: confiance sous seuil ({confidence_score.overall_confidence:.1%} < {threshold:.1%})"
        
        return False, "Recommandation inconnue"


def evaluate_prediction_quality(ensemble_result: Dict, match_data: Dict) -> Dict:
    """
    Fonction utilitaire pour évaluer rapidement une prédiction.
    
    Args:
        ensemble_result: Résultat de l'ensemble
        match_data: Données du match
        
    Returns:
        Dict avec évaluation complète
    """
    scorer = ConfidenceScorer()
    score = scorer.score_prediction(ensemble_result, match_data)
    should_bet, reason = scorer.should_place_bet(score)
    
    return {
        'confidence_score': score.overall_confidence,
        'recommendation': score.recommendation,
        'should_bet': should_bet,
        'reason': reason,
        'explanation': score.explanation,
        'components': score.confidence_components,
        'prediction': ensemble_result.get('prediction'),
        'ensemble_confidence': ensemble_result.get('confidence')
    }


def filter_predictions(predictions_list: list, min_confidence: float = 0.60) -> list:
    """
    Filtre une liste de prédictions selon leur confiance.
    
    Args:
        predictions_list: Liste de dicts avec 'ensemble_result' et 'match_data'
        min_confidence: Seuil minimum
        
    Returns:
        Liste filtrée avec uniquement les prédictions fiables
    """
    scorer = ConfidenceScorer()
    filtered = []
    
    for pred in predictions_list:
        ensemble_result = pred.get('ensemble_result', {})
        match_data = pred.get('match_data', {})
        
        score = scorer.score_prediction(ensemble_result, match_data)
        should_bet, reason = scorer.should_place_bet(score, min_confidence)
        
        if should_bet:
            pred['confidence_evaluation'] = {
                'score': score.overall_confidence,
                'recommendation': score.recommendation,
                'explanation': score.explanation
            }
            filtered.append(pred)
        else:
            logger.info(f"[FILTER] Prédiction filtrée: {reason}")
    
    logger.info(f"[FILTER] {len(filtered)}/{len(predictions_list)} prédictions conservées")
    return filtered
