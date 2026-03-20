import logging
import numpy as np
from . import analyzers

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
    'avantage_domicile',
    'session_position',
    'momentum5_dom', 'momentum5_ext', 'diff_momentum5',
    'forme_raw_dom', 'forme_raw_ext'  # Pour CatBoost
]

# Mapping des labels pour la classification multiclasse
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

def _calc_momentum_5(forme_str):
    """Calcule la moyenne lissée des points sur les 5 derniers matchs."""
    if not forme_str:
        return 0.0
    valeurs = {"V": 3, "N": 1, "D": 0}
    recent = forme_str[-5:]
    if not recent:
        return 0.0
    return sum(valeurs.get(c, 0) for c in recent) / len(recent)


def _extract_features_list(data: dict) -> list:
    """Extrait la liste brute des features (32 éléments)."""
    pts_dom = _safe_float(data.get('pts_dom'))
    pts_ext = _safe_float(data.get('pts_ext'))
    
    forme_dom_str = data.get('forme_dom', '')
    forme_ext_str = data.get('forme_ext', '')
    
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
    
    journee = _safe_float(data.get('journee'), 1.0)
    session_position = journee / 38.0
    
    momentum5_dom = _calc_momentum_5(forme_dom_str)
    momentum5_ext = _calc_momentum_5(forme_ext_str)
    
    feat_values = [
        pts_dom, pts_ext, pts_dom - pts_ext,
        forme_dom_score, forme_ext_score, forme_dom_score - forme_ext_score,
        momentum_dom, momentum_ext, momentum_dom - momentum_ext,
        instabilite_dom, instabilite_ext,
        bp_dom, bc_dom, bp_ext, bc_ext,
        bp_dom - bp_ext, bc_ext - bc_dom,
        cote_1, cote_x, cote_2,
        prob_1, prob_x, prob_2,
        ecart_cotes,
        bonus_h2h,
        1.0, # avantage_domicile
        session_position,
        momentum5_dom, momentum5_ext, momentum5_dom - momentum5_ext,
        forme_dom_str, forme_ext_str  # Raw strings
    ]

    return feat_values

def extract_features(data: dict, as_dataframe: bool = False):
    """
    Extrait un vecteur de features à partir des données d'un match.
    
    Args:
        data: dictionnaire contenant les données du match
        as_dataframe: si True, retourne un DataFrame pandas (utile pour CatBoost/Inference)
        
    Returns:
        np.ndarray ou pd.DataFrame
    """
    feat_values = _extract_features_list(data)

    if as_dataframe:
        import pandas as pd
        return pd.DataFrame([feat_values], columns=FEATURE_NAMES)
    
    # Pour XGBoost (numérique seulement, on ignore les 2 dernières strings)
    return np.array(feat_values[:-2], dtype=np.float32)


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
            'bonus_h2h': 0.0,
        }
        
        # On utilise _extract_features_list pour avoir exactement 32 éléments (y compris strings)
        feat_values = _extract_features_list(data)
        
        data_list.append(feat_values)
        y_list.append(label)
    
    df = pd.DataFrame(data_list, columns=FEATURE_NAMES)
    y = np.array(y_list, dtype=np.int32)
    
    return df, y
