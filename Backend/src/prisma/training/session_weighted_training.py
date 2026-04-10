"""
PRISMA Session-Weighted Training Module
Implémente l'entraînement avec pondération décroissante des sessions
au lieu d'une fenêtre fixe de matchs.
"""
import logging
import numpy as np
import pandas as pd
from typing import List, Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Pondération des sessions par ancienneté
SESSION_WEIGHTS = {
    0: 1.0,   # Session actuelle : poids maximum
    1: 0.7,   # Session N-1 : 70% 
    2: 0.4,   # Session N-2 : 40%
    3: 0.2,   # Session N-3 : 20%
    4: 0.1,   # Session N-4 et plus : 10%
}

def get_session_weight(session_offset: int) -> float:
    """Retourne le poids d'une session selon son offset."""
    return SESSION_WEIGHTS.get(min(session_offset, 4), 0.1)

def extract_weighted_training_data(conn, current_session_id: int, min_matches: int = 300) -> Tuple[pd.DataFrame, np.ndarray]:
    """
    Extrait les données d'entraînement avec pondération par session.
    
    Args:
        conn: Connexion DB active
        current_session_id: ID de la session actuelle
       # XGBoost ne supporte pas les chaînes. On garde seulement les features numériques.
    if hasattr(X, 'iloc'):
        # Garder seulement les 31 premières features (exclure les 2 dernières strings et les 6 nouvelles features pour compatibilité)
        X = X.iloc[:, :-8].values.astype('float32'))
    """
    cursor = conn.cursor()
    
    # Récupérer toutes les sessions complètes avec leurs poids
    cursor.execute("""
        SELECT DISTINCT s.id as session_id, s.timestamp_debut
        FROM sessions s
        WHERE s.id <= %s
        ORDER BY s.id DESC
        LIMIT 10
    """, (current_session_id,))
    
    sessions = cursor.fetchall()
    if not sessions:
        logger.warning("[WEIGHTED_TRAINING] Aucune session trouvée")
        return None, None
    
    # Calculer les offsets et poids
    session_weights = []
    current_idx = next(i for i, s in enumerate(sessions) if s['session_id'] == current_session_id)
    
    for i, session in enumerate(sessions):
        offset = abs(i - current_idx)
        weight = get_session_weight(offset)
        session_weights.append({
            'session_id': session['session_id'],
            'offset': offset,
            'weight': weight
        })
    
    logger.info(f"[WEIGHTED_TRAINING] Sessions trouvées avec poids: {session_weights}")
    
    # Extraire les données de chaque session avec poids
    weighted_data = []
    weighted_labels = []
    total_processed = 0
    from prisma.training.training_status import status_manager
    
    for session_info in session_weights:
        session_id = session_info['session_id']
        weight = session_info['weight']
        
        if weight < 0.05:  # Ignorer sessions trop anciennes
            continue
            
        # Récupérer les matchs de la session
        cursor.execute("""
            SELECT 
                m.id, m.journee, m.session_id,
                m.equipe_dom_id, m.equipe_ext_id, m.score_dom, m.score_ext,
                m.cote_1, m.cote_x, m.cote_2,
                c1.points as pts_dom, c1.forme as forme_dom, c1.buts_pour as bp_dom, c1.buts_contre as bc_dom,
                c2.points as pts_ext, c2.forme as forme_ext, c2.buts_pour as bp_ext, c2.buts_contre as bc_ext
            FROM matches m
            LEFT JOIN (
                SELECT DISTINCT ON (equipe_id, session_id) 
                    equipe_id, session_id, points, forme, buts_pour, buts_contre
                FROM classement
                ORDER BY equipe_id, session_id, journee DESC
            ) c1 ON c1.equipe_id = m.equipe_dom_id AND c1.session_id = m.session_id
            LEFT JOIN (
                SELECT DISTINCT ON (equipe_id, session_id)
                    equipe_id, session_id, points, forme, buts_pour, buts_contre
                FROM classement
                ORDER BY equipe_id, session_id, journee DESC
            ) c2 ON c2.equipe_id = m.equipe_ext_id AND c2.session_id = m.session_id
            WHERE m.session_id = %s
            AND m.score_dom IS NOT NULL AND m.score_ext IS NOT NULL
            ORDER BY m.journee ASC
        """, (session_id,))
        
        matches = cursor.fetchall()
        if not matches:
            continue
            
        status_manager.update_global(
            description=f"Extraction : Session {session_id} ({len(matches)} matchs)..."
        )
        
        # Traiter chaque match de la session
        for match in matches:
            score_dom = match['score_dom']
            score_ext = match['score_ext']
            
            # Déterminer le label
            if score_dom > score_ext:
                label = 0  # '1'
            elif score_dom == score_ext:
                label = 1  # 'X'
            else:
                label = 2  # '2'
            
            # Créer le dictionnaire de données
            data = {
                'journee': match.get('journee', 1.0),
                'session_id': match['session_id'],
                'equipe_dom_id': match['equipe_dom_id'],
                'equipe_ext_id': match['equipe_ext_id'],
                'pts_dom': match.get('pts_dom') or 0,
                'pts_ext': match.get('pts_ext') or 0,
                'forme_dom': match.get('forme_dom') or '',
                'forme_ext': match.get('forme_ext') or '',
                'bp_dom': match.get('bp_dom') or 0,
                'bc_dom': match.get('bc_dom') or 0,
                'bp_ext': match.get('bp_ext') or 0,
                'bc_ext': match.get('bc_ext') or 0,
                'cote_1': match.get('cote_1'),
                'cote_x': match.get('cote_x'),
                'cote_2': match.get('cote_2'),
            }
            
            # Ajouter le bonus H2H
            from prisma.audit import analyzers
            data['bonus_h2h'] = analyzers.analyser_confrontations_directes_prisma(
                cursor, match['session_id'], match['equipe_dom_id'], match['equipe_ext_id']
            )
            
            # Extraire les features
            from prisma import xgboost_features
            feat_values = xgboost_features._extract_features_list(data, conn)
            total_processed += 1
            
            if total_processed % 50 == 0:
                status_manager.update_global(
                    description=f"Processing : {total_processed} matchs extraits..."
                )
            
            # Ajouter les données pondérées
            for _ in range(int(weight * 10)):  # Multiplier par 10 et arrondir
                weighted_data.append(feat_values)
                weighted_labels.append(label)
    
    if not weighted_data or len(weighted_labels) < min_matches:
        logger.warning(f"[WEIGHTED_TRAINING] Pas assez de données pondérées: {len(weighted_labels)}/{min_matches}")
        return None, None
    
    # Créer les DataFrames
    df = pd.DataFrame(weighted_data, columns=xgboost_features.FEATURE_NAMES)
    y = np.array(weighted_labels, dtype=np.int32)
    
    # XGBoost ne supporte pas les chaînes. On garde seulement les features numériques (toutes sauf les formes raw).
    if hasattr(df, 'iloc'):
        # On ne slice plus à 31, on garde tout ce qui est numérique
        X = df.drop(columns=['forme_raw_dom', 'forme_raw_ext'], errors='ignore').values.astype('float32')
    
    # Calculer les statistiques de pondération
    total_samples = len(weighted_labels)
    effective_samples = sum(1 for i in range(total_samples) if i % 10 == 0)  # Compter les échantillons uniques
    
    logger.info(f"[WEIGHTED_TRAINING] Données extraites: {effective_samples} échantillons uniques -> {total_samples} pondérés")
    
    return df, y

def should_retrain_session_weighted(current_session_id: int, last_training_session: int) -> bool:
    """
    Détermine si le réentraînement est nécessaire selon les sessions.
    Plus simple que le comptage de matchs: on réentraîne chaque nouvelle session complétée.
    """
    # Si jamais entraîné, on entraîne
    if last_training_session == 0:
        return True
    
    # Si nouvelle session disponible, on réentraîne
    if current_session_id > last_training_session:
        logger.info(f"[WEIGHTED_TRAINING] Nouvelle session détectée: {last_training_session} -> {current_session_id}")
        return True
    
    return False

def get_training_summary(conn, current_session_id: int) -> dict:
    """Retourne un résumé des données d'entraînement disponibles."""
    cursor = conn.cursor()
    
    # Compter les matchs par session
    cursor.execute("""
        SELECT s.id as session_id, COUNT(m.id) as match_count
        FROM sessions s
        LEFT JOIN matches m ON s.id = m.session_id 
        AND m.score_dom IS NOT NULL AND m.score_ext IS NOT NULL
        WHERE s.id <= %s
        GROUP BY s.id
        ORDER BY s.id DESC
        LIMIT 6
    """, (current_session_id,))
    
    session_stats = cursor.fetchall()
    
    summary = {
        'current_session': current_session_id,
        'sessions_available': len(session_stats),
        'total_matches': sum(s['match_count'] or 0 for s in session_stats),
        'session_breakdown': []
    }
    
    current_idx = next((i for i, s in enumerate(session_stats) if s['session_id'] == current_session_id), -1)
    
    for i, stat in enumerate(session_stats):
        offset = abs(i - current_idx) if current_idx >= 0 else 99
        weight = get_session_weight(offset)
        summary['session_breakdown'].append({
            'session_id': stat['session_id'],
            'match_count': stat['match_count'] or 0,
            'offset': offset,
            'weight': weight,
            'weighted_count': int((stat['match_count'] or 0) * weight)
        })
    
    return summary
