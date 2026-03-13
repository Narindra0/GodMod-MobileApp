#!/usr/bin/env python3
"""
Script pour importer tous les logos des équipes en une seule fois
"""

from update_logos import mettre_a_jour_logo

def importer_tous_les_logos():
    """Importe tous les logos des équipes"""
    
    # Mapping des équipes avec leurs logos
    equipes_logos = {
        "Aston Villa": "https://i.ibb.co/nSL3kbr/A-Villa.png",
        "Bournemouth": "https://i.ibb.co/Xr4YSPXG/Bournemouth.png", 
        "Brentford": "https://i.ibb.co/WpxwgCBY/Brentford.png",
        "Brighton": "https://i.ibb.co/1GryRKMZ/Brighton.png",
        "Burnley": "https://i.ibb.co/XxGDHzvs/Burnley.png",
        "Crystal Palace": "https://i.ibb.co/Wp2N1y1N/C-Palace.png",
        "Everton": "https://i.ibb.co/qMFDtqjc/Everton.png",
        "Fulham": "https://i.ibb.co/Y4qckfs6/Fulham.png",
        "Liverpool": "https://i.ibb.co/nsV4hSvf/Liverpool.png",
        "Leeds": "https://i.ibb.co/5Wxf4vkR/Leeds.png",
        "London Blues": "https://i.ibb.co/SwC4mfWf/London-Blues.png",
        "London Reds": "https://i.ibb.co/Mk1zxtxd/London-Reds.png",
        "Manchester Blue": "https://i.ibb.co/wF7MSBFp/Manchester-Blue.png",
        "Manchester Red": "https://i.ibb.co/V0vzTQsC/Manchester-Red.png",
        "Newcastle": "https://i.ibb.co/4RgpcZT9/Newcastle.png",
        "N. Forest": "https://i.ibb.co/zWSmsQfC/N-Forest.png",
        "Spurs": "https://i.ibb.co/DP9c3dt4/Spurs.png",
        "Sunderland": "https://i.ibb.co/yB036qRS/Sunderland.png",
        "Wolverhampton": "https://i.ibb.co/6VhKcC6/Wolverhampton.png",
        "West Ham": "https://i.ibb.co/c0ndsF5/West-Ham.png"
    }
    
    print("=== IMPORTATION DES LOGOS ===\n")
    
    succes = 0
    echecs = 0
    
    for equipe_nom, logo_url in equipes_logos.items():
        try:
            mettre_a_jour_logo(equipe_nom, logo_url)
            succes += 1
        except Exception as e:
            print(f"❌ Erreur pour {equipe_nom}: {e}")
            echecs += 1
    
    print(f"\n=== RÉSULTAT ===")
    print(f"✅ Succès: {succes} logos mis à jour")
    print(f"❌ Échecs: {echecs} logos")
    print(f"📊 Total: {len(equipes_logos)} équipes traitées")

if __name__ == "__main__":
    importer_tous_les_logos()
