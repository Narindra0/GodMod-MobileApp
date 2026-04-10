"""
PRISMA Prediction Filter Module
Module de filtrage intelligent des prédictions.
Sélectionne les meilleures opportunités selon multiple critères.
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .confidence_scorer import ConfidenceScorer, ConfidenceScore

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """Configuration du filtrage."""
    min_overall_confidence: float = 0.60
    min_model_confidence: float = 0.55
    min_value_score: float = 0.20
    max_market_anomaly: float = 0.50
    require_model_agreement: bool = False
    min_data_quality: float = 0.60
    
    # Filtres par type de match
    exclude_longshots: bool = True  # Exclure cotes > 5.0
    exclude_favorites_extreme: bool = True  # Exclure cotes < 1.15
    prefer_balanced_markets: bool = False  # Préférer marchés équilibrés
    
    # Limites
    max_predictions_per_session: Optional[int] = None
    top_n_by_confidence: Optional[int] = None


class PredictionFilter:
    """
    Filtre intelligent des prédictions PRISMA.
    Applique des règles de filtrage basées sur la confiance, la value, et la qualité.
    """
    
    def __init__(self, config: Optional[FilterConfig] = None):
        self.config = config or FilterConfig()
        self.confidence_scorer = ConfidenceScorer()
    
    def filter_predictions(self, predictions: List[Dict]) -> List[Dict]:
        """
        Filtre une liste de prédictions selon les critères configurés.
        
        Args:
            predictions: Liste de dicts avec 'ensemble_result' et 'match_data'
            
        Returns:
            Liste filtrée triée par confiance décroissante
        """
        if not predictions:
            return []
        
        logger.info(f"[FILTER] Début filtrage: {len(predictions)} prédictions candidates")
        
        scored_predictions = []
        
        # Étape 1: Scorer chaque prédiction
        for pred in predictions:
            ensemble_result = pred.get('ensemble_result', {})
            match_data = pred.get('match_data', {})
            
            # Calculer le score de confiance
            confidence_score = self.confidence_scorer.score_prediction(
                ensemble_result, match_data
            )
            
            # Évaluer les filtres spécifiques
            filters_passed, filter_reasons = self._evaluate_filters(
                confidence_score, ensemble_result, match_data
            )
            
            scored_predictions.append({
                'prediction': pred,
                'confidence_score': confidence_score,
                'filters_passed': filters_passed,
                'filter_reasons': filter_reasons,
                'final_score': confidence_score.overall_confidence if filters_passed else 0.0
            })
        
        # Étape 2: Filtrer les échecs
        passed = [p for p in scored_predictions if p['filters_passed']]
        rejected = [p for p in scored_predictions if not p['filters_passed']]
        
        # Logger les rejets
        for p in rejected[:5]:  # Limiter le logging
            reasons = ', '.join(p['filter_reasons'])
            logger.debug(f"[FILTER] Rejeté: {reasons}")
        
        # Étape 3: Appliquer les limites
        filtered = self._apply_limits(passed)
        
        # Étape 4: Trier par score final
        filtered.sort(key=lambda x: x['final_score'], reverse=True)
        
        # Extraire les prédictions
        result = [p['prediction'] for p in filtered]
        
        # Ajouter les métadonnées d'évaluation
        for i, pred in enumerate(result):
            pred['filter_metadata'] = {
                'confidence_score': filtered[i]['confidence_score'].overall_confidence,
                'recommendation': filtered[i]['confidence_score'].recommendation,
                'rank': i + 1,
                'total_filtered': len(result)
            }
        
        logger.info(f"[FILTER] Résultat: {len(result)}/{len(predictions)} prédictions conservées")
        
        return result
    
    def _evaluate_filters(self, confidence_score: ConfidenceScore, 
                         ensemble_result: Dict, match_data: Dict) -> Tuple[bool, List[str]]:
        """
        Évalue tous les filtres pour une prédiction.
        
        Returns:
            (passed_all, list_of_reasons_if_failed)
        """
        reasons = []
        
        # Filtre 1: Confiance globale minimum
        if confidence_score.overall_confidence < self.config.min_overall_confidence:
            reasons.append(f"confiance_insuffisante({confidence_score.overall_confidence:.2f})")
        
        # Filtre 2: Confiance du modèle
        components = confidence_score.confidence_components
        if components.get('model_confidence', 0) < self.config.min_model_confidence:
            reasons.append(f"confiance_modele_faible({components.get('model_confidence', 0):.2f})")
        
        # Filtre 3: Score de value
        if components.get('value_score', 0) < self.config.min_value_score:
            reasons.append(f"pas_de_value({components.get('value_score', 0):.2f})")
        
        # Filtre 4: Accord des modèles (si requis)
        if self.config.require_model_agreement:
            if components.get('model_agreement', 0) < 0.5:
                reasons.append(f"desaccord_modeles({components.get('model_agreement', 0):.2f})")
        
        # Filtre 5: Qualité des données
        if components.get('data_quality', 1) < self.config.min_data_quality:
            reasons.append(f"donnees_incompletes({components.get('data_quality', 0):.2f})")
        
        # Filtre 6: Anomalie de marché
        cote_1 = match_data.get('cote_1', 2.0)
        cote_x = match_data.get('cote_x', 3.0)
        cote_2 = match_data.get('cote_2', 2.0)
        
        sum_probs = sum(1.0/c for c in [cote_1, cote_x, cote_2] if c > 0)
        overround = sum_probs - 1.0
        
        if overround > self.config.max_market_anomaly:
            reasons.append(f"anomalie_marche({overround:.2f})")
        
        # Filtre 7: Longshots (cotes très élevées)
        if self.config.exclude_longshots:
            max_cote = max(cote_1, cote_x, cote_2)
            if max_cote > 5.0:
                reasons.append(f"longshot_exclu({max_cote:.2f})")
        
        # Filtre 8: Favoris extrêmes (cotes très basses)
        if self.config.exclude_favorites_extreme:
            min_cote = min(cote_1, cote_x, cote_2)
            if min_cote < 1.15:
                reasons.append(f"favori_extreme_exclu({min_cote:.2f})")
        
        passed = len(reasons) == 0
        return passed, reasons
    
    def _apply_limits(self, scored_predictions: List[Dict]) -> List[Dict]:
        """Applique les limites de nombre de prédictions."""
        result = scored_predictions
        
        # Limite totale
        if self.config.max_predictions_per_session:
            result = result[:self.config.max_predictions_per_session]
        
        # Top N par confiance
        if self.config.top_n_by_confidence:
            result = result[:self.config.top_n_by_confidence]
        
        return result
    
    def select_best_predictions(self, predictions: List[Dict], 
                                target_count: int = 5) -> List[Dict]:
        """
        Sélectionne les N meilleures prédictions.
        
        Args:
            predictions: Liste de prédictions
            target_count: Nombre cible de prédictions
            
        Returns:
            Les N meilleures prédictions
        """
        # Config temporaire pour sélectionner exactement target_count
        temp_config = FilterConfig(
            top_n_by_confidence=target_count,
            min_overall_confidence=0.50  # Plus permissif
        )
        
        temp_filter = PredictionFilter(temp_config)
        return temp_filter.filter_predictions(predictions)


def create_conservative_filter() -> PredictionFilter:
    """Crée un filtre conservateur (haute qualité, faible volume)."""
    config = FilterConfig(
        min_overall_confidence=0.70,
        min_model_confidence=0.65,
        min_value_score=0.30,
        require_model_agreement=True,
        exclude_longshots=True,
        exclude_favorites_extreme=True,
        top_n_by_confidence=3
    )
    return PredictionFilter(config)


def create_aggressive_filter() -> PredictionFilter:
    """Crée un filtre agressif (plus de volume, risque plus élevé)."""
    config = FilterConfig(
        min_overall_confidence=0.55,
        min_model_confidence=0.50,
        min_value_score=0.10,
        require_model_agreement=False,
        exclude_longshots=False,
        exclude_favorites_extreme=True,
        top_n_by_confidence=10
    )
    return PredictionFilter(config)


def create_balanced_filter() -> PredictionFilter:
    """Crée un filtre équilibré (défaut recommandé)."""
    return PredictionFilter()  # Utilise les valeurs par défaut


def quick_filter(predictions: List[Dict], strategy: str = 'balanced') -> List[Dict]:
    """
    Filtre rapide avec stratégie prédéfinie.
    
    Args:
        predictions: Liste de prédictions
        strategy: 'conservative', 'balanced', ou 'aggressive'
        
    Returns:
        Prédictions filtrées
    """
    filters = {
        'conservative': create_conservative_filter(),
        'balanced': create_balanced_filter(),
        'aggressive': create_aggressive_filter()
    }
    
    filter_obj = filters.get(strategy, create_balanced_filter())
    return filter_obj.filter_predictions(predictions)
