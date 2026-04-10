"""
PRISMA Market Features Module
Features avancées basées sur l'analyse des cotes bookmakers.
Extrait la valeur implicite, détecte les anomalies de marché, et calcule les scores de value.
"""

import logging
from typing import Dict, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class MarketFeatureExtractor:
    """
    Extracteur de features basées sur le marché (cotes, probabilités implicites).
    Utilise les insights de l'audit statistique pour pondérer les features.
    """
    
    def __init__(self, conn=None):
        self.conn = conn
        # Seuils calibrés selon l'audit
        self.value_threshold = 0.05  # 5% edge minimum
        self.confidence_high_threshold = 0.65
        self.confidence_low_threshold = 0.35
        
    def extract_all_market_features(self, match_data: Dict) -> Dict[str, float]:
        """
        Extrait toutes les features de marché pour un match.
        
        Args:
            match_data: Dict avec cote_1, cote_x, cote_2, et optionnellement features existantes
            
        Returns:
            Dict de features numériques
        """
        cote_1 = match_data.get('cote_1', 2.0)
        cote_x = match_data.get('cote_x', 3.0)
        cote_2 = match_data.get('cote_2', 2.0)
        
        features = {}
        
        # 1. Probabilités implicites normalisées
        prob_1, prob_x, prob_2, sum_prob = self._calculate_implied_probabilities(cote_1, cote_x, cote_2)
        features['prob_implicite_1'] = prob_1
        features['prob_implicite_x'] = prob_x
        features['prob_implicite_2'] = prob_2
        features['sum_prob'] = sum_prob
        features['overround'] = sum_prob - 1.0  # Marge bookmaker
        
        # 2. Entropie de distribution (mesure d'incertitude)
        features['entropy'] = self._calculate_entropy(prob_1, prob_x, prob_2)
        
        # 3. Features de favoritisme
        min_cote = min(cote_1, cote_x, cote_2)
        max_cote = max(cote_1, cote_x, cote_2)
        features['favorite_odds'] = min_cote
        features['underdog_odds'] = max_cote
        features['odds_spread'] = max_cote - min_cote
        features['odds_ratio'] = max_cote / min_cote if min_cote > 0 else 1.0
        
        # 4. Classification du type de match selon cotes
        features['odds_range_class'] = self._classify_odds_range(min_cote)
        
        # 5. Détection d'équilibre du marché
        features['is_balanced_market'] = 1.0 if self._is_balanced_market(cote_1, cote_x, cote_2) else 0.0
        
        # 6. Anomalie de marché (cotes suspectes)
        features['market_anomaly_score'] = self._detect_market_anomaly(cote_1, cote_x, cote_2)
        
        # 7. Score de value (si données historiques disponibles)
        if self.conn and 'equipe_dom_id' in match_data:
            value_score = self._calculate_value_score(match_data, prob_1, prob_x, prob_2)
            features['value_score_1'] = value_score.get('1', 0.0)
            features['value_score_x'] = value_score.get('X', 0.0)
            features['value_score_2'] = value_score.get('2', 0.0)
            features['max_value_score'] = max(value_score.values()) if value_score else 0.0
        
        # 8. Confiance du marché (inverse de l'entropie normalisée)
        features['market_confidence'] = 1.0 - (features['entropy'] / np.log(3))
        
        # 9. Différence par rapport à probabilités uniformes
        uniform_prob = 1.0 / 3.0
        features['prob_deviation_1'] = prob_1 - uniform_prob
        features['prob_deviation_x'] = prob_x - uniform_prob
        features['prob_deviation_2'] = prob_2 - uniform_prob
        
        # 10. Kelly Criterion implications
        features['kelly_fraction_1'] = self._calculate_kelly_fraction(prob_1, cote_1)
        features['kelly_fraction_x'] = self._calculate_kelly_fraction(prob_x, cote_x)
        features['kelly_fraction_2'] = self._calculate_kelly_fraction(prob_2, cote_2)
        
        # 11. Double Chance probabilities (Si disponibles dans match_data)
        cote_1x = match_data.get('cote_1x')
        cote_12 = match_data.get('cote_12')
        cote_x2 = match_data.get('cote_x2')
        
        if cote_1x:
            features['prob_implicite_1x'] = 1.0 / cote_1x
        else:
            # Fallback direct: P(1X) = P(1) + P(X)
            features['prob_implicite_1x'] = prob_1 + prob_x
            
        if cote_12:
            features['prob_implicite_12'] = 1.0 / cote_12
        else:
            features['prob_implicite_12'] = prob_1 + prob_2
            
        if cote_x2:
            features['prob_implicite_x2'] = 1.0 / cote_x2
        else:
            features['prob_implicite_x2'] = prob_x + prob_2
            
        return features
    
    def _calculate_implied_probabilities(self, cote_1: float, cote_x: float, cote_2: float) -> Tuple[float, float, float, float]:
        """Calcule les probabilités implicites avec normalisation."""
        raw_1 = 1.0 / cote_1 if cote_1 > 0 else 0
        raw_x = 1.0 / cote_x if cote_x > 0 else 0
        raw_2 = 1.0 / cote_2 if cote_2 > 0 else 0
        
        sum_raw = raw_1 + raw_x + raw_2
        
        if sum_raw == 0:
            return 0.33, 0.33, 0.34, 1.0
        
        # Normaliser pour somme = 1
        norm_1 = raw_1 / sum_raw
        norm_x = raw_x / sum_raw
        norm_2 = raw_2 / sum_raw
        
        return norm_1, norm_x, norm_2, sum_raw
    
    def _calculate_entropy(self, p1: float, px: float, p2: float) -> float:
        """Calcule l'entropie de Shannon (mesure d'incertitude)."""
        probs = [p1, px, p2]
        entropy = 0.0
        for p in probs:
            if p > 0:
                entropy -= p * np.log(p)
        return entropy
    
    def _classify_odds_range(self, min_cote: float) -> int:
        """
        Classifie le match selon la cote du favori.
        
        Returns:
            0: Favorite (< 1.5) - Favori clair
            1: Likely (1.5 - 2.2) - Probable
            2: Balanced (2.2 - 3.0) - Équilibré
            3: Underdog (3.0 - 5.0) - Outsider
            4: Longshot (> 5.0) - Très improbable
        """
        if min_cote < 1.5:
            return 0
        elif min_cote < 2.2:
            return 1
        elif min_cote < 3.0:
            return 2
        elif min_cote < 5.0:
            return 3
        else:
            return 4
    
    def _is_balanced_market(self, cote_1: float, cote_x: float, cote_2: float) -> bool:
        """Détecte si c'est un match équilibré selon les cotes."""
        min_cote = min(cote_1, cote_x, cote_2)
        max_cote = max(cote_1, cote_x, cote_2)
        
        # Si l'écart entre min et max est < 1.5, c'est équilibré
        return (max_cote - min_cote) < 1.5
    
    def _detect_market_anomaly(self, cote_1: float, cote_x: float, cote_2: float) -> float:
        """
        Détecte les anomalies de marché.
        
        Returns:
            Score d'anomalie (0 = normal, > 0.5 = suspect)
        """
        anomaly_score = 0.0
        
        # Anomalie 1: Cotes trop resserrées (sum prob < 1.02)
        probs = [1.0/c if c > 0 else 0 for c in [cote_1, cote_x, cote_2]]
        sum_prob = sum(probs)
        if sum_prob < 1.02:
            anomaly_score += 0.3
        
        # Anomalie 2: Cotes trop dispersées (sum prob > 1.2)
        if sum_prob > 1.2:
            anomaly_score += 0.3
        
        # Anomalie 3: Cote nulle > 2x cote 1 (inversion anormale)
        if cote_x > cote_1 * 2.0 and cote_x > cote_2 * 2.0:
            anomaly_score += 0.2
        
        # Anomalie 4: Cotes quasi-identiques (manipulation suspecte)
        if max(abs(cote_1 - cote_x), abs(cote_x - cote_2), abs(cote_1 - cote_2)) < 0.1:
            anomaly_score += 0.2
        
        return min(anomaly_score, 1.0)
    
    def _calculate_value_score(self, match_data: Dict, prob_1: float, prob_x: float, prob_2: float) -> Dict[str, float]:
        """
        Calcule le score de value pour chaque résultat.
        Nécessite une connexion DB pour accéder aux stats historiques.
        """
        if not self.conn:
            return {'1': 0.0, 'X': 0.0, '2': 0.0}
        
        try:
            cursor = self.conn.cursor()
            
            # Récupérer les probabilités historiques par tranche de cotes
            cote_ranges = {
                '1': match_data.get('cote_1', 2.0),
                'X': match_data.get('cote_x', 3.0),
                '2': match_data.get('cote_2', 2.0)
            }
            
            value_scores = {}
            
            for outcome, cote in cote_ranges.items():
                prob_implied = 1.0 / cote
                
                # Trouver la win rate historique pour cette tranche de cotes
                cursor.execute("""
                    SELECT COUNT(*) as total, 
                           SUM(CASE WHEN m.score_dom > m.score_ext AND %s = '1' THEN 1
                                    WHEN m.score_dom = m.score_ext AND %s = 'X' THEN 1
                                    WHEN m.score_dom < m.score_ext AND %s = '2' THEN 1
                                    ELSE 0 END) as wins
                    FROM matches m
                    WHERE m.cote_1 BETWEEN %s AND %s
                    AND m.score_dom IS NOT NULL
                """, (outcome, outcome, outcome, cote * 0.9, cote * 1.1))
                
                result = cursor.fetchone()
                if result and result['total'] > 20:
                    historical_prob = result['wins'] / result['total']
                    # Value = (probabilité historique - probabilité implicite) * cote
                    value = (historical_prob - prob_implied) * cote
                    value_scores[outcome] = max(value, -1.0)  # Cap négatif
                else:
                    value_scores[outcome] = 0.0
            
            cursor.close()
            return value_scores
            
        except Exception as e:
            logger.warning(f"[MARKET_FEATURES] Erreur calcul value score: {e}")
            return {'1': 0.0, 'X': 0.0, '2': 0.0}
    
    def _calculate_kelly_fraction(self, probability: float, odds: float) -> float:
        """
        Calcule la fraction Kelly pour un pari.
        f* = (bp - q) / b
        où b = odds - 1, p = probabilité estimée, q = 1-p
        """
        if odds <= 1.0 or probability <= 0:
            return 0.0
        
        b = odds - 1.0
        q = 1.0 - probability
        
        kelly = (b * probability - q) / b
        
        # Kelly fractionnaire (half-kelly pour réduire volatilité)
        return max(0.0, kelly * 0.5)
    
    def get_market_sentiment(self, match_data: Dict) -> Dict:
        """
        Analyse le sentiment du marché pour un match.
        
        Returns:
            Dict avec interpretation du marché
        """
        cote_1 = match_data.get('cote_1', 2.0)
        cote_x = match_data.get('cote_x', 3.0)
        cote_2 = match_data.get('cote_2', 2.0)
        
        features = self.extract_all_market_features(match_data)
        
        sentiment = {
            'market_favorite': None,
            'market_confidence_level': 'medium',
            'market_balance': 'balanced',
            'value_opportunity': None,
            'recommendation': 'analyze'
        }
        
        # Déterminer le favori du marché
        probs = [features['prob_implicite_1'], features['prob_implicite_x'], features['prob_implicite_2']]
        max_prob_idx = np.argmax(probs)
        sentiment['market_favorite'] = ['1', 'X', '2'][max_prob_idx]
        
        # Niveau de confiance
        if features['market_confidence'] > 0.7:
            sentiment['market_confidence_level'] = 'high'
        elif features['market_confidence'] < 0.4:
            sentiment['market_confidence_level'] = 'low'
        
        # Équilibre
        if features['is_balanced_market']:
            sentiment['market_balance'] = 'balanced'
        elif features['odds_spread'] > 3.0:
            sentiment['market_balance'] = 'unbalanced_favorite'
        else:
            sentiment['market_balance'] = 'slight_favorite'
        
        # Opportunité de value
        if features.get('max_value_score', 0) > self.value_threshold:
            sentiment['value_opportunity'] = True
            sentiment['recommendation'] = 'value_bet'
        
        # Anomalie
        if features['market_anomaly_score'] > 0.5:
            sentiment['recommendation'] = 'caution'
        
        return sentiment


def integrate_market_features_into_xgboost_features(match_data: Dict, conn=None) -> Dict:
    """
    Fonction d'intégration pour enrichir les données avec les features de marché.
    À appeler depuis xgboost_features.py
    
    Args:
        match_data: Données de match existantes
        conn: Connexion DB optionnelle
        
    Returns:
        match_data enrichi avec les nouvelles features
    """
    extractor = MarketFeatureExtractor(conn)
    market_features = extractor.extract_all_market_features(match_data)
    
    # Fusionner avec les données existantes
    enriched_data = {**match_data, **market_features}
    
    return enriched_data


def should_bet_based_on_market(match_data: Dict, min_value_threshold: float = 0.05) -> Tuple[bool, str]:
    """
    Décide si on doit parier sur ce match basé sur l'analyse de marché.
    
    Args:
        match_data: Données du match
        min_value_threshold: Seuil minimum de value (5% par défaut)
        
    Returns:
        (should_bet: bool, reason: str)
    """
    extractor = MarketFeatureExtractor()
    sentiment = extractor.get_market_sentiment(match_data)
    features = extractor.extract_all_market_features(match_data)
    
    # Filtrer les matchs avec anomalie forte
    if features['market_anomaly_score'] > 0.7:
        return False, "market_anomaly_detected"
    
    # Filtrer les marchés très incertains
    if features['market_confidence'] < 0.3:
        return False, "market_uncertainty_too_high"
    
    # Filtrer si pas de value
    if features.get('max_value_score', 0) < min_value_threshold:
        return False, "insufficient_value"
    
    # OK pour parier
    return True, f"value_detected_{features['max_value_score']:.2f}"


# Liste des noms de features pour intégration dans FEATURE_NAMES
MARKET_FEATURE_NAMES = [
    'overround', 'entropy', 'odds_spread', 'odds_ratio',
    'market_confidence', 'market_anomaly_score',
    'prob_deviation_1', 'prob_deviation_x', 'prob_deviation_2',
    'value_score_1', 'value_score_x', 'value_score_2', 'max_value_score',
    'kelly_fraction_1', 'kelly_fraction_x', 'kelly_fraction_2',
    'odds_range_class', 'is_balanced_market'
]
