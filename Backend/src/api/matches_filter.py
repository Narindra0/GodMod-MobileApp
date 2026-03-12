"""
Filtre pour extraire les matchs à venir avec ID local et cotes
Garde : équipes, journée, cotes 1X2, ID local

Version: 2.1
Date: Janvier 2025
"""

import json
from typing import List, Dict
import requests
from .api_client import URL_MATCHS, HEADERS

# ==================== CONFIG ====================

ROUND_LIMIT = 1  # Nombre de journées à récupérer par défaut

# ==================== FONCTION D'EXTRACTION ====================

def extract_matches_with_local_ids(data: Dict, limit: int = 1) -> List[Dict]:
    """
    Extrait les matchs avec un ID local par journée
    
    Structure de sortie:
    [
        {
            "roundNumber": 1,
            "expectedStart": "2025-01-15T14:00:00Z",
            "matches": [
                {
                    "matchId": 1,  # ID local (1 → N)
                    "name": "Équipe A vs Équipe B",
                    "homeTeam": "Équipe A",
                    "awayTeam": "Équipe B",
                    "round": "1",
                    "odds": [
                        {"type": "1", "odds": 2.50},
                        {"type": "X", "odds": 3.20},
                        {"type": "2", "odds": 2.80}
                    ]
                }
            ]
        }
    ]
    
    Args:
        data: Données brutes de l'API
        limit: Nombre de journées à extraire
    
    Returns:
        Liste filtrée des matchs
    """
    # Filtrage J38 : La journée 38 est systématiquement ignorée (Exception métier)
    rounds_raw = data.get("rounds", [])
    rounds_valid = [r for r in rounds_raw if r.get("roundNumber") != 38]
    
    # Trier les rounds par numéro et limiter
    rounds = sorted(
        rounds_valid,
        key=lambda r: r.get("roundNumber", 0)
    )[:limit]
    
    output = []
    
    for r in rounds:
        clean_round = {
            "roundNumber": r.get("roundNumber"),
            "expectedStart": r.get("expectedStart"),
            "matches": []
        }
        
        # Création d'ID LOCAL par journée (1 → N)
        for local_id, m in enumerate(r.get("matches", []), start=1):
            odds = []
            
            # Extraction des cotes 1X2
            for bet_type in m.get("eventBetTypes", []):
                if bet_type.get("name") == "1X2":
                    for item in bet_type.get("eventBetTypeItems", []):
                        odds.append({
                            "type": item.get("shortName"),
                            "odds": item.get("odds")
                        })
            
            clean_match = {
                "matchId": local_id,   # ID LOCAL
                "name": m.get("name"),
                "homeTeam": m.get("homeTeam", {}).get("name"),
                "awayTeam": m.get("awayTeam", {}).get("name"),
                "round": str(r.get("roundNumber")),
                "odds": odds
            }
            
            clean_round["matches"].append(clean_match)
        
        output.append(clean_round)
    
    return output


def get_filtered_matches(limit: int = 1) -> List[Dict]:
    """
    Récupère et filtre les matchs à venir en une seule fonction
    
    Args:
        limit: Nombre de journées à récupérer
    
    Returns:
        Matchs filtrés avec ID local
    """
    try:
        response = requests.get(URL_MATCHS, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        raw_data = response.json()
        return extract_matches_with_local_ids(raw_data, limit)
    
    except requests.exceptions.RequestException as e:
        print(f"[ERREUR] Impossible de recuperer les matchs : {e}")
        return []


# ==================== TEST ====================

if __name__ == "__main__":
    print("[TEST] Module Matches Filter")
    print("=" * 60)
    
    # Test avec l'API directement
    print("\n[TEST 1] Recuperation et filtrage des matchs a venir...")
    clean_data = get_filtered_matches(limit=2)  # 2 journées pour le test
    
    if clean_data:
        print(f"[OK] {len(clean_data)} journees filtrees")
        
        # Afficher les détails
        for round_data in clean_data:
            print(f"\n[JOURNEE {round_data['roundNumber']}] {len(round_data['matches'])} matchs")
            
            for match in round_data['matches'][:3]:  # Afficher 3 premiers matchs
                odds_str = ", ".join([f"{o['type']}={o['odds']}" for o in match['odds']])
                print(f"  [{match['matchId']}] {match['homeTeam']} vs {match['awayTeam']}")
                print(f"      Cotes: {odds_str}")
        
        # Sauvegarder pour vérification
        with open("test_matches_filtered.json", 'w', encoding='utf-8') as f:
            json.dump(clean_data, f, indent=2, ensure_ascii=False)
        print("\n[SAVED] Fichier test_matches_filtered.json cree")
        
        # Statistiques de compression
        raw_response = requests.get(URL_MATCHS, headers=HEADERS, timeout=10)
        raw_size = len(raw_response.text)
        filtered_size = len(json.dumps(clean_data))
        reduction = ((raw_size - filtered_size) / raw_size) * 100
        
        print(f"\n[STATS] Compression des donnees:")
        print(f"  Taille brute: {raw_size:,} bytes")
        print(f"  Taille filtree: {filtered_size:,} bytes")
        print(f"  Reduction: {reduction:.1f}%")
    else:
        print("[ERREUR] Echec de la recuperation")
    
    print("\n" + "=" * 60)
    print("[SUCCESS] Test termine")
