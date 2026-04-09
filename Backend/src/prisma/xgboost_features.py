import logging
import numpy as np
import sys
import os
from prisma import analyzers
from prisma.market_features import MarketFeatureExtractor, MARKET_FEATURE_NAMES

logger = logging.getLogger(__name__)

# Noms des features dans l'ordre attendu par le modèle
FEATURE_NAMES = [
    'pts_dom', 'pts_ext', 'diff_points',
    'forme_dom', 'forme_ext', 'diff_forme',
    'momentum_dom', 'momentum_ext', 'diff_momentum',
    'instabilite_dom', 'instabilite_ext',
    'bp_dom', 'bc_dom', 'bp_ext', 'bc_ext',
    'diff_attaque', 'diff_defense',
    'cote_1', 'cote_x', 'cote_2',
    'prob_implicite_1', 'prob_implicite_x', 'prob_implicite_2',
    'ecart_cotes',
    'bonus_h2h',
    'match_equilibre',
    'cotes_suspectes',
    'session_position',
    'momentum5_dom', 'momentum5_ext', 'diff_momentum5',
    'forme_raw_dom', 'forme_raw_ext',  # Pour CatBoost
    # Features avancées de classement
    'rang_classement_dom', 'rang_classement_ext',
    'ecart_leader_dom', 'ecart_leader_ext',
    'zone_classement_dom', 'zone_classement_ext',
    'pression_fin_session',
    'force_relative_dom_ext',  # Matrice de force relative
    # NOUVELLES: Features de marché avancées
    'overround', 'entropy', 'odds_spread', 'odds_ratio',
    'market_confidence', 'market_anomaly_score',
    'prob_deviation_1', 'prob_deviation_x', 'prob_deviation_2',
    'value_score_1', 'value_score_x', 'value_score_2', 'max_value_score',
    'kelly_fraction_1', 'kelly_fraction_x', 'kelly_fraction_2',
    'odds_range_class', 'is_balanced_market'
]

# Mapping des labels pour la classification multiclasse
# Caractéristiques numériques seulement (pour XGBoost et LightGBM)
NUMERIC_FEATURE_NAMES = [name for name in FEATURE_NAMES if name not in ['forme_raw_dom', 'forme_raw_ext']]

LABEL_MAP = {'1': 0, 'X': 1, '2': 2}
LABEL_MAP_INV = {0: '1', 1: 'X', 2: '2'}


def _safe_float(val, default=0.0):
    """Convertit une valeur en float de manière sécurisée."""
    try:
        if val is None:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def _get_classement_position(cursor, session_id: int, equipe_id: int, journee: int) -> dict:
    """Extrait la position au classement et l'écart avec le leader."""
    try:
        # Récupérer le classement à la journée précédente
        cursor.execute("""
            SELECT points, position
            FROM classement 
            WHERE session_id = %s AND equipe_id = %s AND journee <= %s
            ORDER BY journee DESC LIMIT 1
        """, (session_id, equipe_id, journee - 1))
        
        team_result = cursor.fetchone()
        if not team_result:
            return {'rang': 11, 'points': 0, 'ecart_leader': 0}  # Valeurs par défaut
        
        # Récupérer le leader
        cursor.execute("""
            SELECT MAX(points) as max_points
            FROM classement 
            WHERE session_id = %s AND journee <= %s
        """, (session_id, journee - 1))
        
        leader_result = cursor.fetchone()
        leader_points = leader_result['max_points'] if leader_result else 0
        
        rang = team_result['position'] or 11
        points = team_result['points'] or 0
        ecart_leader = leader_points - points
        
        return {
            'rang': rang,
            'points': points,
            'ecart_leader': ecart_leader
        }
    except Exception as e:
        logger.warning(f"[FEATURES] Erreur classement position: {e}")
        return {'rang': 11, 'points': 0, 'ecart_leader': 0}

def _get_zone_classement(rang: int) -> int:
    """Convertit le rang en zone de classement (TOP5/MIDDLE/RELEGATION)."""
    if rang <= 5:
        return 2  # TOP5
    elif rang >= 16:
        return 0  # RELEGATION
    else:
        return 1  # MIDDLE

def _calc_pression_fin_session(journee: float) -> float:
    """Calcule la pression en fin de session (plus élevée vers J38)."""
    return max(0.0, (journee - 28) / 10.0)  # Commence après J28, max 1.0 à J38

def _calc_momentum_5(forme_str):
    """Calcule la moyenne lissée des points sur les 5 derniers matchs."""
    if not forme_str:
        return 0.0
    valeurs = {"V": 3, "N": 1, "D": 0}
    recent = forme_str[-5:]
    if not recent:
        return 0.0
    return sum(valeurs.get(c, 0) for c in recent) / len(recent)


def _extract_features_list(data: dict, conn=None) -> list:
    """Extrait la liste brute des features (57 éléments avec nouvelles features de marché)."""
    # Sécurité: vérifier que pts_dom et pts_ext sont des nombres
    def safe_int(val):
        try:
            return int(float(val)) if val is not None else 0
        except (ValueError, TypeError):
            return 0
    
    # Récupération des valeurs avec gestion d'erreur renforcée
    pts_dom_raw = data.get('pts_dom')
    pts_ext_raw = data.get('pts_ext')
    
    # Si les valeurs sont des strings qui ressemblent à des formes (V, N, D), on met 0
    if isinstance(pts_dom_raw, str) and len(pts_dom_raw) >= 4 and all(c in 'VND' for c in pts_dom_raw):
        pts_dom = 0
    else:
        pts_dom = safe_int(pts_dom_raw)
    
    if isinstance(pts_ext_raw, str) and len(pts_ext_raw) >= 4 and all(c in 'VND' for c in pts_ext_raw):
        pts_ext = 0
    else:
        pts_ext = safe_int(pts_ext_raw)
    
    forme_dom_str = data.get('forme_dom', '') or ''
    forme_ext_str = data.get('forme_ext', '') or ''
    
    forme_dom_score = float(analyzers.pondere_forme_prisma(forme_dom_str))
    forme_ext_score = float(analyzers.pondere_forme_prisma(forme_ext_str))
    
    momentum_dom = float(analyzers.calculer_momentum_prisma(forme_dom_str))
    momentum_ext = float(analyzers.calculer_momentum_prisma(forme_ext_str))
    
    instabilite_dom = 1.0 if analyzers.detecter_instabilite_prisma(forme_dom_str) else 0.0
    instabilite_ext = 1.0 if analyzers.detecter_instabilite_prisma(forme_ext_str) else 0.0
    
    bp_dom = _safe_float(data.get('bp_dom'))
    bc_dom = _safe_float(data.get('bc_dom'))
    bp_ext = _safe_float(data.get('bp_ext'))
    bc_ext = _safe_float(data.get('bc_ext'))
    
    cote_1 = _safe_float(data.get('cote_1'), 2.0)
    cote_x = _safe_float(data.get('cote_x'), 3.0)
    cote_2 = _safe_float(data.get('cote_2'), 2.0)
    
    prob_1 = 1.0 / cote_1 if cote_1 > 0 else 0.0
    prob_x = 1.0 / cote_x if cote_x > 0 else 0.0
    prob_2 = 1.0 / cote_2 if cote_2 > 0 else 0.0
    
    ecart_cotes = abs(cote_1 - cote_2)
    bonus_h2h = _safe_float(data.get('bonus_h2h'))
    
    # Features ML issues de l'expertise métier
    match_equilibre = 1.0 if analyzers.detecter_match_equilibre_prisma(cote_1, cote_x, cote_2) else 0.0
    cotes_suspectes = float(analyzers.analyser_cotes_suspectes_prisma(cote_1, cote_x, cote_2))
    
    journee = _safe_float(data.get('journee'), 1.0)
    session_position = journee / 38.0
    
    momentum5_dom = _calc_momentum_5(forme_dom_str)
    momentum5_ext = _calc_momentum_5(forme_ext_str)
    
    # --- Features avancées de classement ---
    rang_dom = 11
    rang_ext = 11
    ecart_leader_dom = 0
    ecart_leader_ext = 0
    force_relative = 1.0
    
    # Récupérer les positions au classement si connexion disponible
    if conn and 'session_id' in data and 'equipe_dom_id' in data:
        try:
            session_id = data['session_id']
            equipe_dom_id = data['equipe_dom_id']
            equipe_ext_id = data['equipe_ext_id']
            
            cursor = conn.cursor()
            
            # Position domicile
            pos_dom = _get_classement_position(cursor, session_id, equipe_dom_id, journee)
            rang_dom = pos_dom['rang']
            ecart_leader_dom = pos_dom['ecart_leader']
            
            # Position extérieur
            pos_ext = _get_classement_position(cursor, session_id, equipe_ext_id, journee)
            rang_ext = pos_ext['rang']
            ecart_leader_ext = pos_ext['ecart_leader']
            
            # Force relative depuis la matrice
            try:
                from prisma.team_strength_matrix import get_relative_strength
            except ImportError:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                from prisma.team_strength_matrix import get_relative_strength
            force_relative = get_relative_strength(equipe_dom_id, equipe_ext_id)
            
        except Exception as e:
            logger.warning(f"[FEATURES] Erreur extraction features avancées: {e}")
    
    # Zones de classement
    zone_dom = _get_zone_classement(rang_dom)
    zone_ext = _get_zone_classement(rang_ext)
    
    # Pression fin de session
    pression = _calc_pression_fin_session(journee)
    
    # --- NOUVELLES: Features de marché avancées ---
    market_extractor = MarketFeatureExtractor(conn)
    market_features = market_extractor.extract_all_market_features({
        'cote_1': cote_1,
        'cote_x': cote_x,
        'cote_2': cote_2,
        'equipe_dom_id': data.get('equipe_dom_id'),
        'equipe_ext_id': data.get('equipe_ext_id'),
        'session_id': data.get('session_id')
    })
    
    feat_values = [
        # Features de base (0-20)
        pts_dom, pts_ext, pts_dom - pts_ext,
        forme_dom_score, forme_ext_score, forme_dom_score - forme_ext_score,
        momentum_dom, momentum_ext, momentum_dom - momentum_ext,
        instabilite_dom, instabilite_ext,
        bp_dom, bc_dom, bp_ext, bc_ext,
        bp_dom - bp_ext, bc_ext - bc_dom,
        cote_1, cote_x, cote_2,
        # Probabilités et features cotes (21-28)
        prob_1, prob_x, prob_2,
        ecart_cotes,
        bonus_h2h,
        match_equilibre,
        cotes_suspectes,
        session_position,
        # Momentum (29-31)
        momentum5_dom, momentum5_ext, momentum5_dom - momentum5_ext,
        # Forme raw pour CatBoost (32-33)
        forme_dom_str, forme_ext_str,
        # Features classement avancées (34-43)
        rang_dom, rang_ext,
        ecart_leader_dom, ecart_leader_ext,
        zone_dom, zone_ext,
        pression,
        force_relative,
        # NOUVELLES: Features de marché (44-56)
        market_features.get('overround', 0.0),
        market_features.get('entropy', 1.0),
        market_features.get('odds_spread', 1.0),
        market_features.get('odds_ratio', 1.0),
        market_features.get('market_confidence', 0.5),
        market_features.get('market_anomaly_score', 0.0),
        market_features.get('prob_deviation_1', 0.0),
        market_features.get('prob_deviation_x', 0.0),
        market_features.get('prob_deviation_2', 0.0),
        market_features.get('value_score_1', 0.0),
        market_features.get('value_score_x', 0.0),
        market_features.get('value_score_2', 0.0),
        market_features.get('max_value_score', 0.0),
        market_features.get('kelly_fraction_1', 0.0),
        market_features.get('kelly_fraction_x', 0.0),
        market_features.get('kelly_fraction_2', 0.0),
        market_features.get('odds_range_class', 2.0),
        market_features.get('is_balanced_market', 1.0)
    ]

    return feat_values

def get_numeric_features(feat_values):
    """Filtre les features pour ne garder que le向量 numérique (57 éléments)."""
    # Indices 31 et 32 sont forme_raw_dom et forme_raw_ext
    return feat_values[:31] + feat_values[33:]


def extract_features(data: dict, as_dataframe: bool = False, conn=None):
    """
    Extrait un vecteur de features à partir des données d'un match.
    
    Args:
        data: dictionnaire contenant les données du match
        as_dataframe: si True, retourne un DataFrame pandas (utile pour CatBoost/Inference)
        conn: connexion DB pour features avancées (optionnel)
        
    Returns:
        np.ndarray ou pd.DataFrame
    """
    feat_values = _extract_features_list(data, conn)

    if as_dataframe:
        import pandas as pd
        return pd.DataFrame([feat_values], columns=FEATURE_NAMES)
    
    # Pour XGBoost (numérique seulement: 57 features, exclut les 2 strings forme_raw)
    # Features 0-30: base features (numériques)
    # Features 31-32: forme_raw strings (à exclure pour XGBoost)
    # Features 33-56: features avancées (numériques)
    numeric_features = feat_values[:31] + feat_values[33:]  # Exclut indices 31-32 (strings)
    return np.array(numeric_features, dtype=np.float32)


def extract_training_data(conn, session_id: int = None):
    """
    Extrait les données d'entraînement. Retourne un DataFrame pour CatBoost.
    """
    import pandas as pd
    cursor = conn.cursor()
    
    query = """
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
        WHERE m.score_dom IS NOT NULL AND m.score_ext IS NOT NULL
    """
    params = []
    if session_id:
        query += " AND m.session_id = %s"
        params.append(session_id)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    if not rows:
        return None, None
    
    data_list = []
    y_list = []
    
    for row in rows:
        score_dom = row['score_dom']
        score_ext = row['score_ext']
        
        if score_dom > score_ext:
            label = LABEL_MAP['1']
        elif score_dom == score_ext:
            label = LABEL_MAP['X']
        else:
            label = LABEL_MAP['2']
        
        data = {
            'journee': row.get('journee', 1.0),
            'session_id': row.get('session_id'),
            'equipe_dom_id': row.get('equipe_dom_id'),
            'equipe_ext_id': row.get('equipe_ext_id'),
            'pts_dom': row.get('pts_dom') or 0,
            'pts_ext': row.get('pts_ext') or 0,
            'forme_dom': row.get('forme_dom') or '',
            'forme_ext': row.get('forme_ext') or '',
            'bp_dom': row.get('bp_dom') or 0,
            'bc_dom': row.get('bc_dom') or 0,
            'bp_ext': row.get('bp_ext') or 0,
            'bc_ext': row.get('bc_ext') or 0,
            'cote_1': row.get('cote_1'),
            'cote_x': row.get('cote_x'),
            'cote_2': row.get('cote_2'),
            'bonus_h2h': analyzers.analyser_confrontations_directes_prisma(
                cursor, row['session_id'], row['equipe_dom_id'], row['equipe_ext_id']
            ),
        }
        
        # On utilise _extract_features_list pour avoir exactement 39 éléments avec nouvelles features
        feat_values = _extract_features_list(data, conn)
        
        data_list.append(feat_values)
        y_list.append(label)
    
    df = pd.DataFrame(data_list, columns=FEATURE_NAMES)
    y = np.array(y_list, dtype=np.int32)
    
    return df, y
