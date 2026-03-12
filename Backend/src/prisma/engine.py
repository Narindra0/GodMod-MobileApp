from . import analyzers

def calculer_score_prisma(data):
    """
    Calcule le score de confiance PRISMA pour un match.
    
    Args:
        data: Dictionnaire contenant:
            - pts_dom, pts_ext
            - forme_dom, forme_ext
            - buts_pour_dom, buts_contre_dom
            - buts_pour_ext, buts_contre_ext
            - cote_1, cote_x, cote_2
            - bonus_h2h
            
    Returns:
        Tuple (prediction, score_final)
    """
    # 1. CLASSEMENT (40%)
    score_classement = (data['pts_dom'] - data['pts_ext']) * 0.4
    
    # 2. FORME (30%)
    f_dom_score = analyzers.pondere_forme_prisma(data['forme_dom'])
    f_ext_score = analyzers.pondere_forme_prisma(data['forme_ext'])
    score_forme = (f_dom_score - f_ext_score) * 0.3
    
    # 3. BUTS (15%)
    score_buts = 0
    if all(k in data for k in ['bp_dom', 'bc_dom', 'bp_ext', 'bc_ext']):
        diff_attaque = (data['bp_dom'] - data['bp_ext']) * 0.1
        diff_defense = (data['bc_ext'] - data['bc_dom']) * 0.1
        score_buts = (diff_attaque + diff_defense) * 0.15
        
    # 4. DOMICILE (10%)
    avantage_domicile = 2.0
    
    score_base = score_classement + score_forme + score_buts + avantage_domicile
    
    # --- FILTRES DE REJET ---
    if analyzers.detecter_instabilite_prisma(data['forme_dom']) or analyzers.detecter_instabilite_prisma(data['forme_ext']):
        return None, "REJET_INSTABILITE"
        
    if analyzers.detecter_match_equilibre_prisma(data['cote_1'], data['cote_x'], data['cote_2']):
        return None, "REJET_EQUILIBRE"
        
    # --- BONUS/MALUS ---
    bonus_cotes = analyzers.analyser_cotes_suspectes_prisma(data['cote_1'], data['cote_x'], data['cote_2'])
    if bonus_cotes <= -3.0:
        return None, "REJET_PIEGE_COTES"
        
    bonus_h2h = data.get('bonus_h2h', 0)
    if bonus_h2h <= -2.5:
        return None, "REJET_H2H_DEFAVORABLE"
        
    momentum_dom = analyzers.calculer_momentum_prisma(data['forme_dom'])
    momentum_ext = analyzers.calculer_momentum_prisma(data['forme_ext'])
    bonus_momentum = (momentum_dom - momentum_ext) * 0.5
    
    score_final = score_base + bonus_h2h + bonus_cotes + bonus_momentum
    
    # Seuils
    SEUIL_VICTOIRE = 7.0
    SEUIL_NUL_MAX = 3.0
    SEUIL_NUL_MIN = -3.0
    
    if score_final > SEUIL_VICTOIRE:
        return "1", score_final
    elif score_final < -SEUIL_VICTOIRE:
        return "2", abs(score_final)
    elif SEUIL_NUL_MIN <= score_final <= SEUIL_NUL_MAX:
        return "X", abs(score_final)
    
    return None, "ZONE_INCERTITUDE"
