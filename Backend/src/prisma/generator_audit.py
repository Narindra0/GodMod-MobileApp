"""
PRISMA Generator Audit Module
Module d'audit statistique complet pour analyser les données historiques de matchs.
Objectif : Identifier patterns, biais, corrélations cotes-résultats et anomalies.
"""

import logging
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict, Counter
import numpy as np
from decimal import Decimal

logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """Encoder JSON personnalisé pour gérer les Decimal."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class GeneratorAuditor:
    """
    Auditeur statistique pour le générateur de données bookmakers.
    Analyse la distribution, les corrélations et les patterns séquentiels.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.audit_results = {
            'metadata': {
                'audit_timestamp': datetime.now().isoformat(),
                'total_matches': 0,
                'audit_duration_ms': 0
            },
            'error': None
        }
        
    def run_full_audit(self) -> Dict[str, Any]:
        """
        Exécute un audit complet de toutes les données historiques.
        
        Returns:
            Dict contenant tous les résultats d'audit
        """
        logger.info("=" * 80)
        logger.info("[AUDIT] DÉMARRAGE AUDIT STATISTIQUE COMPLET")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        
        # Récupérer toutes les données
        matches_data = self._fetch_all_historical_matches()
        total_matches = len(matches_data)
        
        if total_matches == 0:
            logger.warning("[AUDIT] Aucune donnée historique trouvée")
            self.audit_results['error'] = 'no_data'
            return self.audit_results
        
        logger.info(f"[AUDIT] {total_matches} matchs trouvés pour analyse")
        
        # Analyses principales
        self.audit_results = {
            'metadata': {
                'audit_timestamp': datetime.now().isoformat(),
                'total_matches': total_matches,
                'audit_duration_ms': None
            },
            'distribution_analysis': self._analyze_result_distribution(matches_data),
            'odds_correlation': self._analyze_odds_correlation(matches_data),
            'temporal_patterns': self._analyze_temporal_patterns(matches_data),
            'sequential_patterns': self._analyze_sequential_patterns(matches_data),
            'odds_ranges': self._analyze_odds_ranges(matches_data),
            'anomalies': self._detect_anomalies(matches_data),
            'value_opportunities': self._identify_value_opportunities(matches_data),
            'feature_candidates': []
        }
        
        # Extraire les features candidates
        self.audit_results['feature_candidates'] = self._extract_feature_candidates()
        
        # Calculer durée
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() * 1000
        self.audit_results['metadata']['audit_duration_ms'] = duration
        
        logger.info("=" * 80)
        logger.info(f"[AUDIT] TERMINÉ en {duration:.0f}ms")
        logger.info("=" * 80)
        
        return self.audit_results
    
    def _fetch_all_historical_matches(self) -> List[Dict]:
        """Récupère tous les matchs historiques avec leurs résultats."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                m.id, m.session_id, m.journee,
                m.equipe_dom_id, m.equipe_ext_id,
                m.cote_1, m.cote_x, m.cote_2,
                m.score_dom, m.score_ext,
                s.timestamp_debut, s.current_day as session_total_days
            FROM matches m
            JOIN sessions s ON m.session_id = s.id
            WHERE m.score_dom IS NOT NULL 
            AND m.score_ext IS NOT NULL
            AND m.cote_1 IS NOT NULL
            AND m.cote_x IS NOT NULL
            AND m.cote_2 IS NOT NULL
            ORDER BY m.session_id, m.journee
        """)
        
        matches = cursor.fetchall()
        cursor.close()
        
        # Enrichir avec le résultat 1/X/2
        enriched = []
        for match in matches:
            score_dom = match['score_dom']
            score_ext = match['score_ext']
            
            if score_dom > score_ext:
                result = '1'
            elif score_dom == score_ext:
                result = 'X'
            else:
                result = '2'
            
            match_dict = dict(match)
            match_dict['result'] = result
            match_dict['prob_1'] = 1.0 / float(match['cote_1']) if match['cote_1'] > 0 else 0
            match_dict['prob_x'] = 1.0 / float(match['cote_x']) if match['cote_x'] > 0 else 0
            match_dict['prob_2'] = 1.0 / float(match['cote_2']) if match['cote_2'] > 0 else 0
            match_dict['sum_prob'] = match_dict['prob_1'] + match_dict['prob_x'] + match_dict['prob_2']
            
            enriched.append(match_dict)
        
        return enriched
    
    def _analyze_result_distribution(self, matches: List[Dict]) -> Dict:
        """Analyse la distribution réelle des résultats 1/X/2."""
        results = [m['result'] for m in matches]
        counter = Counter(results)
        total = len(results)
        
        distribution = {
            '1': {'count': counter['1'], 'percentage': counter['1'] / total * 100},
            'X': {'count': counter['X'], 'percentage': counter['X'] / total * 100},
            '2': {'count': counter['2'], 'percentage': counter['2'] / total * 100}
        }
        
        # Test d'équilibre (théorique ~33% chacun pour distribution parfaite)
        expected = total / 3
        chi2 = sum((counter[r] - expected) ** 2 / expected for r in ['1', 'X', '2'])
        
        analysis = {
            'distribution': distribution,
            'total_matches': total,
            'chi2_test': chi2,
            'is_balanced': chi2 < 5.99,  # Seuil 95% pour ddl=2
            'deviation_from_uniform': {
                '1': distribution['1']['percentage'] - 33.33,
                'X': distribution['X']['percentage'] - 33.33,
                '2': distribution['2']['percentage'] - 33.33
            }
        }
        
        logger.info(f"[AUDIT] Distribution: 1={distribution['1']['percentage']:.1f}%, "
                   f"X={distribution['X']['percentage']:.1f}%, "
                   f"2={distribution['2']['percentage']:.1f}%")
        logger.info(f"[AUDIT] Distribution équilibrée: {analysis['is_balanced']} (χ²={chi2:.2f})")
        
        return analysis
    
    def _analyze_odds_correlation(self, matches: List[Dict]) -> Dict:
        """
        Analyse la corrélation entre cotes implicites et résultats réels.
        Si corrélation > 85%, les cotes sont très informatives.
        """
        # Calculer l'accuracy des probabilités implicites
        correct_predictions = 0
        prob_predictions = []
        
        for match in matches:
            probs = {
                '1': float(match['prob_1']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33,
                'X': float(match['prob_x']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33,
                '2': float(match['prob_2']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33
            }
            
            # La cote avec plus haute probabilité implicite
            predicted = max(probs, key=probs.get)
            prob_predictions.append(predicted)
            
            if predicted == match['result']:
                correct_predictions += 1
        
        accuracy = correct_predictions / len(matches)
        
        # Calculer Brier Score (plus faible = meilleur)
        brier_scores = []
        for match in matches:
            probs = {
                '1': float(match['prob_1']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33,
                'X': float(match['prob_x']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33,
                '2': float(match['prob_2']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33
            }
            
            # Brier score pour ce match
            outcome = {r: 1.0 if r == match['result'] else 0.0 for r in ['1', 'X', '2']}
            brier = sum((probs[r] - outcome[r]) ** 2 for r in ['1', 'X', '2']) / 3
            brier_scores.append(brier)
        
        avg_brier = sum(brier_scores) / len(brier_scores)
        
        # Calibration : compter dans combien de cas la prob implicite reflète la vraie fréquence
        calibration_bins = self._calculate_calibration(matches)
        
        analysis = {
            'odds_accuracy': accuracy,
            'odds_accuracy_percentage': accuracy * 100,
            'is_highly_predictive': accuracy > 0.50,  # Seuil: cotes prédissent mieux que random
            'brier_score': float(avg_brier),
            'brier_interpretation': 'good' if avg_brier < 0.2 else 'fair' if avg_brier < 0.25 else 'poor',
            'calibration_by_probability': calibration_bins,
            'recommendation': 'HIGH_PRIORITY' if accuracy > 0.52 else 'MEDIUM_PRIORITY' if accuracy > 0.48 else 'LOW_PRIORITY'
        }
        
        logger.info(f"[AUDIT] Corrélation cotes: Accuracy={accuracy*100:.1f}%, "
                   f"Brier={avg_brier:.3f}, Priorité={analysis['recommendation']}")
        
        return analysis
    
    def _calculate_calibration(self, matches: List[Dict]) -> Dict:
        """Calcule la calibration des probabilités par bins."""
        bins = defaultdict(lambda: {'predicted': [], 'actual': []})
        
        for match in matches:
            probs = {
                '1': float(match['prob_1']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33,
                'X': float(match['prob_x']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33,
                '2': float(match['prob_2']) / float(match['sum_prob']) if match['sum_prob'] > 0 else 0.33
            }
            
            for outcome, prob in probs.items():
                bin_key = int(prob * 10) / 10  # 0.0, 0.1, 0.2, ..., 0.9
                bins[bin_key]['predicted'].append(prob)
                actual = 1.0 if outcome == match['result'] else 0.0
                bins[bin_key]['actual'].append(actual)
        
        calibration = {}
        for bin_key in sorted(bins.keys()):
            data = bins[bin_key]
            if len(data['predicted']) >= 10:  # Minimum pour fiabilité
                avg_predicted = sum(data['predicted']) / len(data['predicted'])
                avg_actual = sum(data['actual']) / len(data['actual'])
                calibration[f"{bin_key:.1f}"] = {
                    'count': len(data['predicted']),
                    'avg_predicted': avg_predicted,
                    'avg_actual': avg_actual,
                    'calibration_error': abs(avg_predicted - avg_actual)
                }
        
        return calibration
    
    def _analyze_temporal_patterns(self, matches: List[Dict]) -> Dict:
        """Analyse les patterns temporels (début vs fin de session)."""
        # Grouper par position dans la session
        early_matches = [m for m in matches if m['journee'] <= 10]
        mid_matches = [m for m in matches if 11 <= m['journee'] <= 25]
        late_matches = [m for m in matches if m['journee'] > 25]
        
        def get_distribution(match_list):
            results = [m['result'] for m in match_list]
            counter = Counter(results)
            total = len(results)
            return {r: counter[r] / total * 100 if total > 0 else 0 for r in ['1', 'X', '2']}
        
        early_dist = get_distribution(early_matches)
        mid_dist = get_distribution(mid_matches)
        late_dist = get_distribution(late_matches)
        
        analysis = {
            'early_phase': {
                'journees': '1-10',
                'match_count': len(early_matches),
                'distribution': early_dist
            },
            'mid_phase': {
                'journees': '11-25',
                'match_count': len(mid_matches),
                'distribution': mid_dist
            },
            'late_phase': {
                'journees': '26+',
                'match_count': len(late_matches),
                'distribution': late_dist
            },
            'temporal_variance': {
                'home_advantage_early_vs_late': early_dist['1'] - late_dist['1'],
                'draw_variance': max(early_dist['X'], mid_dist['X'], late_dist['X']) - min(early_dist['X'], mid_dist['X'], late_dist['X'])
            }
        }
        
        logger.info(f"[AUDIT] Patterns temporels: "
                   f"Early 1={early_dist['1']:.1f}%, "
                   f"Late 1={late_dist['1']:.1f}%, "
                   f"Avantage domicile évolue de {analysis['temporal_variance']['home_advantage_early_vs_late']:+.1f}%")
        
        return analysis
    
    def _analyze_sequential_patterns(self, matches: List[Dict]) -> Dict:
        """
        Détecte les patterns séquentiels (runs, alternances).
        Utile pour créer des features de "mémoire" du système.
        """
        # Trier par session et journée
        sorted_matches = sorted(matches, key=lambda x: (x['session_id'], x['journee']))
        
        # Grouper par session
        sessions = defaultdict(list)
        for match in sorted_matches:
            sessions[match['session_id']].append(match['result'])
        
        # Analyser les runs
        run_lengths = {'1': [], 'X': [], '2': []}
        max_runs = {'1': 0, 'X': 0, '2': 0}
        
        for session_results in sessions.values():
            if len(session_results) < 3:
                continue
            
            current_run = 1
            for i in range(1, len(session_results)):
                if session_results[i] == session_results[i-1]:
                    current_run += 1
                else:
                    outcome = session_results[i-1]
                    run_lengths[outcome].append(current_run)
                    max_runs[outcome] = max(max_runs[outcome], current_run)
                    current_run = 1
            
            # Dernier run
            outcome = session_results[-1]
            run_lengths[outcome].append(current_run)
            max_runs[outcome] = max(max_runs[outcome], current_run)
        
        # Calculer stats des runs
        run_stats = {}
        for outcome in ['1', 'X', '2']:
            lengths = run_lengths[outcome]
            if lengths:
                run_stats[outcome] = {
                    'avg_run_length': sum(lengths) / len(lengths),
                    'max_run_length': max(lengths),
                    'total_runs': len(lengths)
                }
        
        # Détecter alternances (patterns V-D-V-D ou X-V-X-V)
        alternation_count = 0
        total_transitions = 0
        
        for session_results in sessions.values():
            for i in range(1, len(session_results)):
                total_transitions += 1
                if session_results[i] != session_results[i-1]:
                    alternation_count += 1
        
        alternation_rate = alternation_count / total_transitions if total_transitions > 0 else 0
        
        analysis = {
            'run_statistics': run_stats,
            'max_consecutive': max_runs,
            'alternation_rate': alternation_rate,
            'is_random_like': 0.45 < alternation_rate < 0.55,  # Random ~50% alternance
            'sequential_memory_detected': any(max_runs[o] > 4 for o in max_runs)
        }
        
        logger.info(f"[AUDIT] Patterns séquentiels: "
                   f"Max runs 1={max_runs['1']}, X={max_runs['X']}, 2={max_runs['2']}, "
                   f"Alternance={alternation_rate*100:.1f}%")
        
        if analysis['sequential_memory_detected']:
            logger.info("[AUDIT] ⚠️ Mémoire séquentielle détectée - Opportunité de feature!")
        
        return analysis
    
    def _analyze_odds_ranges(self, matches: List[Dict]) -> Dict:
        """Analyse la performance par tranches de cotes."""
        ranges = {
            'favorite': {'cote_max': 1.50, 'matches': []},  # Favori clair
            'likely': {'cote_max': 2.20, 'matches': []},     # Probable
            'balanced': {'cote_max': 3.00, 'matches': []},   # Équilibré
            'underdog': {'cote_max': 5.00, 'matches': []},  # Outsider
            'longshot': {'cote_max': 999, 'matches': []}     # Très improbable
        }
        
        for match in matches:
            min_cote = min(float(match['cote_1']), float(match['cote_x']), float(match['cote_2']))
            
            for range_name, range_def in ranges.items():
                if min_cote <= range_def['cote_max']:
                    range_def['matches'].append(match)
                    break
        
        range_analysis = {}
        for range_name, range_def in ranges.items():
            matches_in_range = range_def['matches']
            if not matches_in_range:
                continue
            
            results = [m['result'] for m in matches_in_range]
            counter = Counter(results)
            total = len(results)
            
            # Calculer la précision si on avait parié le favori (cote min)
            favorite_wins = sum(1 for m in matches_in_range 
                            if (m['cote_1'] == min(m['cote_1'], m['cote_x'], m['cote_2']) and m['result'] == '1')
                            or (m['cote_2'] == min(m['cote_1'], m['cote_x'], m['cote_2']) and m['result'] == '2'))
            
            range_analysis[range_name] = {
                'match_count': total,
                'percentage_of_total': total / len(matches) * 100,
                'distribution': {r: counter[r] / total * 100 for r in ['1', 'X', '2']},
                'favorite_accuracy': favorite_wins / total * 100 if total > 0 else 0,
                'avg_min_odds': sum(min(m['cote_1'], m['cote_x'], m['cote_2']) for m in matches_in_range) / total
            }
        
        logger.info(f"[AUDIT] Tranches cotes: "
                   f"Favoris={range_analysis.get('favorite', {}).get('match_count', 0)} "
                   f"(précision fav={range_analysis.get('favorite', {}).get('favorite_accuracy', 0):.1f}%)")
        
        return range_analysis
    
    def _detect_anomalies(self, matches: List[Dict]) -> List[Dict]:
        """Détecte les anomalies statistiques."""
        anomalies = []
        
        # Anomalie 1: Cotes trop resserrées (sum < 1.05 ou sum > 1.15)
        for match in matches:
            if float(match['sum_prob']) < 1.05 or float(match['sum_prob']) > 1.15:
                anomalies.append({
                    'type': 'suspicious_odds_sum',
                    'match_id': match['id'],
                    'session_id': match['session_id'],
                    'sum_prob': match['sum_prob'],
                    'severity': 'medium'
                })
        
        # Anomalie 2: Résultats très surprenants (cote > 5 qui gagne)
        surprises = []
        for match in matches:
            result_cote = float(match[f'cote_{match["result"].lower().replace("x", "x")}'])
            if result_cote > 5.0:
                surprises.append({
                    'match_id': match['id'],
                    'cote': result_cote,
                    'result': match['result']
                })
        
        if len(surprises) > len(matches) * 0.05:  # > 5% de surprises majeures
            anomalies.append({
                'type': 'high_surprise_rate',
                'count': len(surprises),
                'percentage': len(surprises) / len(matches) * 100,
                'severity': 'high' if len(surprises) > len(matches) * 0.08 else 'medium'
            })
        
        # Anomalie 3: Sessions avec distribution très biaisée
        sessions = defaultdict(lambda: Counter())
        for match in matches:
            sessions[match['session_id']][match['result']] += 1
        
        for session_id, dist in sessions.items():
            total = sum(dist.values())
            if total < 10:
                continue
            max_pct = max(dist.values()) / total
            if max_pct > 0.55:  # > 55% d'un seul résultat
                anomalies.append({
                    'type': 'biased_session',
                    'session_id': session_id,
                    'dominant_result': dist.most_common(1)[0][0],
                    'dominant_percentage': max_pct * 100,
                    'severity': 'medium'
                })
        
        logger.info(f"[AUDIT] Anomalies détectées: {len(anomalies)} "
                   f"({sum(1 for a in anomalies if a.get('severity') == 'high')} high, "
                   f"{sum(1 for a in anomalies if a.get('severity') == 'medium')} medium)")
        
        return anomalies
    
    def _identify_value_opportunities(self, matches: List[Dict]) -> Dict:
        """
        Identifie les opportunités de value betting.
        Où les cotes sont sous-évaluées par rapport à la fréquence réelle.
        """
        # Grouper par tranche de cotes
        odds_bins = defaultdict(lambda: {'count': 0, 'wins': 0})
        
        for match in matches:
            for outcome in ['1', 'X', '2']:
                cote = float(match[f'cote_{outcome.lower().replace("x", "x")}'])
                prob = 1.0 / cote
                bin_key = round(prob * 10) / 10  # 0.1, 0.2, ..., 0.9
                
                odds_bins[bin_key]['count'] += 1
                if match['result'] == outcome:
                    odds_bins[bin_key]['wins'] += 1
        
        value_opportunities = []
        for bin_key, data in odds_bins.items():
            if data['count'] < 20:  # Minimum pour fiabilité
                continue
            
            implied_prob = bin_key
            actual_prob = data['wins'] / data['count']
            edge = actual_prob - implied_prob
            
            if edge > 0.05:  # Edge > 5%
                value_opportunities.append({
                    'implied_probability_range': f"{bin_key:.1f}-{bin_key+0.1:.1f}",
                    'match_count': data['count'],
                    'actual_win_rate': actual_prob,
                    'edge_percentage': edge * 100,
                    'value_rating': 'HIGH' if edge > 0.10 else 'MEDIUM'
                })
        
        # Trier par edge
        value_opportunities.sort(key=lambda x: x['edge_percentage'], reverse=True)
        
        analysis = {
            'opportunities': value_opportunities[:10],  # Top 10
            'total_opportunities': len(value_opportunities),
            'has_value_potential': len(value_opportunities) > 0
        }
        
        if value_opportunities:
            top = value_opportunities[0]
            logger.info(f"[AUDIT] Value détectée: Tranche {top['implied_probability_range']} "
                       f"avec edge +{top['edge_percentage']:.1f}%")
        
        return analysis
    
    def _extract_feature_candidates(self) -> List[Dict]:
        """Extrait les recommandations de nouvelles features basées sur l'audit."""
        candidates = []
        
        # Candidate 1: Si corrélation cotes élevée
        odds_corr = self.audit_results.get('odds_correlation', {})
        if odds_corr.get('is_highly_predictive'):
            candidates.append({
                'name': 'odds_implied_weighted',
                'type': 'feature_engineering',
                'priority': 'HIGH',
                'description': 'Pondérer les features par la fiabilité des cotes implicites',
                'expected_impact': '+3-5% accuracy'
            })
        
        # Candidate 2: Si patterns temporels détectés
        temporal = self.audit_results.get('temporal_patterns', {})
        variance = temporal.get('temporal_variance', {})
        if abs(variance.get('home_advantage_early_vs_late', 0)) > 3:
            candidates.append({
                'name': 'session_phase_adjusted_features',
                'type': 'feature_engineering',
                'priority': 'HIGH',
                'description': 'Features adaptées selon early/mid/late phase de session',
                'expected_impact': '+2-4% accuracy'
            })
        
        # Candidate 3: Si mémoire séquentielle
        sequential = self.audit_results.get('sequential_patterns', {})
        if sequential.get('sequential_memory_detected'):
            candidates.append({
                'name': 'run_detection_features',
                'type': 'feature_engineering',
                'priority': 'MEDIUM',
                'description': 'Détecter les séries en cours (VVV, DDD) comme features',
                'expected_impact': '+1-3% accuracy'
            })
        
        # Candidate 4: Si value opportunities
        value = self.audit_results.get('value_opportunities', {})
        if value.get('has_value_potential'):
            candidates.append({
                'name': 'value_bet_scorer',
                'type': 'prediction_filter',
                'priority': 'HIGH',
                'description': 'Score de value pour filtrer les prédictions',
                'expected_impact': '+5-8% precision on filtered subset'
            })
        
        # Candidate 5: Toujours pertinent
        candidates.append({
            'name': 'odds_range_classifier',
            'type': 'feature_engineering',
            'priority': 'MEDIUM',
            'description': 'Classifier le match selon tranche de cotes (favorite/likely/etc)',
            'expected_impact': '+2-3% accuracy'
        })
        
        # Candidate 6: Anomalies comme feature
        if self.audit_results.get('anomalies'):
            candidates.append({
                'name': 'market_anomaly_flag',
                'type': 'feature_engineering',
                'priority': 'LOW',
                'description': 'Flag si le match présente des cotes anormales',
                'expected_impact': '+1-2% accuracy'
            })
        
        logger.info(f"[AUDIT] {len(candidates)} features candidates identifiées")
        for c in candidates:
            logger.info(f"  - {c['name']} ({c['priority']}): {c['description']}")
        
        return candidates
    
    def generate_audit_report(self, output_path: Optional[str] = None) -> str:
        """
        Génère un rapport d'audit complet en JSON et optionnellement Markdown.
        
        Args:
            output_path: Chemin pour sauvegarder le rapport JSON
            
        Returns:
            Rapport formaté en Markdown
        """
        # Si l'audit n'a pas encore été fait (clé absente), le lancer
        if 'distribution_analysis' not in self.audit_results and self.audit_results.get('error') is None:
            self.run_full_audit()
        
        # Sauvegarde JSON
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.audit_results, f, indent=2, ensure_ascii=False, cls=DecimalEncoder)
            logger.info(f"[AUDIT] Rapport JSON sauvegardé: {output_path}")
        
        # Génération Markdown
        report = self._format_markdown_report()
        return report
    
    def _format_markdown_report(self) -> str:
        """Formate le rapport en Markdown."""
        r = self.audit_results
        
        if r.get('error') == 'no_data' or 'metadata' not in r:
            return f"""# Rapport d'Audit PRISMA (Indisponible)
            
**Date**: {datetime.now().isoformat()}

⚠️ **Aucune donnée historique trouvée pour l'analyse.**
Le système nécessite au moins quelques matchs terminés avec scores et cotes pour générer un audit statistique.

*Veuillez patienter que le système accumule des résultats.*
"""

        meta = r.get('metadata', {})
        dist = r.get('distribution_analysis')
        odds = r.get('odds_correlation')
        
        if not dist or not odds:
            return f"""# Rapport d'Audit PRISMA (Données manquantes)
            
**Date**: {datetime.now().isoformat()}

⚠️ **Les données d'analyse sont manquantes.**
L'audit n'a pas pu générer les statistiques nécessaires.

*Veuillez vérifier les logs pour plus de détails.*
"""
        
        md = f"""# Rapport d'Audit PRISMA

**Date**: {meta['audit_timestamp']}  
**Matchs analysés**: {meta['total_matches']}  
**Durée**: {meta['audit_duration_ms']:.0f}ms

---

## 1. Distribution des Résultats

| Résultat | Count | Pourcentage | Écart vs 33.3% |
|----------|-------|-------------|----------------|
| 1 (Domicile) | {dist['distribution']['1']['count']} | {dist['distribution']['1']['percentage']:.1f}% | {dist['deviation_from_uniform']['1']:+.1f}% |
| X (Nul) | {dist['distribution']['X']['count']} | {dist['distribution']['X']['percentage']:.1f}% | {dist['deviation_from_uniform']['X']:+.1f}% |
| 2 (Extérieur) | {dist['distribution']['2']['count']} | {dist['distribution']['2']['percentage']:.1f}% | {dist['deviation_from_uniform']['2']:+.1f}% |

**Distribution équilibrée**: {'✅ Oui' if dist['is_balanced'] else '❌ Non'} (χ² = {dist['chi2_test']:.2f})

---

## 2. Corrélation Cotes → Résultats

**Accuracy des cotes**: {odds['odds_accuracy_percentage']:.1f}%  
**Brier Score**: {odds['brier_score']:.3f} ({odds['brier_interpretation']})  
**Priorité recommandée**: {odds['recommendation']}

**Interprétation**:
- Si accuracy > 52%: Les cotes sont **très informatives**, doivent être feature prioritaire
- Si 48-52%: Les cotes ont une **valeur modérée**
- Si < 48%: Les cotes sont **peu fiables**, focus sur autres features

---

## 3. Features Candidates Recommandées

"""
        
        for i, candidate in enumerate(r['feature_candidates'], 1):
            priority_emoji = '🔴' if candidate['priority'] == 'HIGH' else '🟡' if candidate['priority'] == 'MEDIUM' else '🟢'
            md += f"""
### {i}. {priority_emoji} {candidate['name']}
- **Type**: {candidate['type']}
- **Priorité**: {candidate['priority']}
- **Description**: {candidate['description']}
- **Impact attendu**: {candidate['expected_impact']}
"""
        
        md += f"""

---

## 4. Prochaines Étapes Recommandées

1. **Semaine 1**: Implémenter les features HIGH priority identifiées
2. **Semaine 2**: Intégrer LightGBM et tester le stacking
3. **Semaine 3**: Valider le gain de précision sur back-test

---

*Généré par PRISMA Generator Auditor*
"""
        
        return md


def run_audit_report(conn, output_path: str = None) -> str:
    """
    Fonction utilitaire pour exécuter un audit complet et générer le rapport.
    
    Args:
        conn: Connexion DB active
        output_path: Chemin optionnel pour sauvegarder le rapport JSON
        
    Returns:
        Rapport Markdown formaté
    """
    auditor = GeneratorAuditor(conn)
    report = auditor.generate_audit_report(output_path)
    return report


if __name__ == "__main__":
    # Test standalone
    import sys
    sys.path.insert(0, 'f:/Narindra Projet/GODMOD version mobile/Backend/src')
    from core.database import get_db_connection
    
    with get_db_connection() as conn:
        report = run_audit_report(conn, 'audit_results.json')
        print(report)
