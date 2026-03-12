import logging

logger = logging.getLogger(__name__)

def pondere_forme_prisma(forme_str):
    """
    Pondération de la forme : les 2 derniers matchs comptent 1.5x plus.
    """
    valeurs = {'V': 3, 'N': 1, 'D': 0}
    if not forme_str or len(forme_str) < 5:
        return sum(valeurs.get(c, 0) for c in (forme_str[-5:] if forme_str else ""))
    
    forme_recente = forme_str[-5:]
    total = 0
    for i, res in enumerate(forme_recente):
        multiplicateur = 1.5 if i >= 3 else 1.0
        total += valeurs.get(res, 0) * multiplicateur
    return total

def detecter_instabilite_prisma(forme):
    """
    Détecte les patterns d'instabilité (alternance V/D).
    """
    if not forme or len(forme) < 3:
        return False
    patterns = ['VDV', 'DVD', 'VNV', 'DND', 'VDVD', 'DVDV']
    for p in patterns:
        if forme.endswith(p):
            return True
    return False

def calculer_momentum_prisma(forme):
    """
    Calcule le momentum basé sur les séries de victoires/défaites.
    """
    if not forme or len(forme) < 3:
        return 0
    if forme.endswith('VVV'): return 3.0
    if forme.endswith('VV'): return 1.5
    if forme.endswith('DDD'): return -3.0
    if forme.endswith('DD'): return -1.5
    return 0

def detecter_match_equilibre_prisma(c1, cx, c2):
    """
    Détecte si les cotes sont trop proches (match imprévisible).
    """
    if None in (c1, cx, c2): return False
    return abs(c1 - c2) < 0.3 and abs(c1 - cx) < 0.4 and abs(c2 - cx) < 0.4

def analyser_cotes_suspectes_prisma(c1, cx, c2):
    """
    Détecte les pièges à cotes et zones idéales.
    """
    if None in (c1, cx, c2): return 0
    c_min = min(c1, c2)
    ecart = abs(c1 - c2)
    
    if c_min < 1.30: return -3.0
    if ecart < 0.3: return -1.5
    if 1.50 <= c_min <= 2.20: return 2.0
    return 0
