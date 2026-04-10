import logging

logger = logging.getLogger(__name__)


def pondere_forme_prisma(forme_str):
    valeurs = {"V": 3, "N": 1, "D": 0}
    if not forme_str or len(forme_str) < 5:
        return sum(valeurs.get(c, 0) for c in (forme_str[-5:] if forme_str else ""))
    forme_recente = forme_str[-5:]
    total = 0
    for i, res in enumerate(forme_recente):
        multiplicateur = 1.5 if i >= 3 else 1.0
        total += valeurs.get(res, 0) * multiplicateur
    return total


def detecter_instabilite_prisma(forme):
    if not forme or len(forme) < 3:
        return False
    patterns = ["VDV", "DVD", "VNV", "DND", "VDVD", "DVDV"]
    for p in patterns:
        if forme.endswith(p):
            return True
    return False


def calculer_momentum_prisma(forme):
    if not forme or len(forme) < 3:
        return 0
    if forme.endswith("VVV"):
        return 3.0
    if forme.endswith("VV"):
        return 1.5
    if forme.endswith("DDD"):
        return -3.0
    if forme.endswith("DD"):
        return -1.5
    return 0


def detecter_match_equilibre_prisma(c1, cx, c2):
    if None in (c1, cx, c2):
        return False
    return abs(c1 - c2) < 0.3 and abs(c1 - cx) < 0.4 and abs(c2 - cx) < 0.4


def analyser_cotes_suspectes_prisma(c1, cx, c2):
    if None in (c1, cx, c2):
        return 0
    c_min = min(c1, c2)
    ecart = abs(c1 - c2)
    if c_min < 1.30:
        return -3.0
    if ecart < 0.3:
        return -1.5
    if 1.50 <= c_min <= 2.20:
        return 2.0
    return 0


def analyser_confrontations_directes_prisma(cursor, session_id, equipe_dom_id, equipe_ext_id):
    """Calcule le bonus H2H basé sur l'historique de la session."""
    cursor.execute("""
        SELECT score_dom, score_ext FROM matches 
        WHERE session_id = %s AND equipe_dom_id = %s AND equipe_ext_id = %s AND score_dom IS NOT NULL
        ORDER BY journee DESC LIMIT 5
    """, (session_id, equipe_dom_id, equipe_ext_id))
    hist = cursor.fetchall()
    if not hist or len(hist) < 3: return 0
    v_dom = sum(1 for h in hist if h['score_dom'] > h['score_ext'])
    nuls = sum(1 for h in hist if h['score_dom'] == h['score_ext'])
    t_vic = v_dom / len(hist)
    if t_vic >= 0.80: return 3.0
    if t_vic >= 0.60: return 1.5
    if (nuls / len(hist)) >= 0.60: return -2.0
    if t_vic <= 0.20: return -3.0
    return 0
