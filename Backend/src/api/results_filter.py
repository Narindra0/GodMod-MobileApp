"""
Filtre pour extraire uniquement les données essentielles des résultats
Garde : équipes, score final, journée

Version: 2.1
Date: Janvier 2025
"""

import json
from typing import List, Dict
import requests
from .api_client import URL_RESULTS, HEADERS

# ==================== FONCTION DE FILTRAGE ====================

def extract_results_minimal(data: Dict) -> List[Dict]:
    """
    Extrait uniquement les informations essentielles des résultats
    
    Structure de sortie:
    [
        {
            "roundNumber": 1,
            "matches": [
                {
                    "id": "match_123",
                    "homeTeam": "Équipe A",
                    "awayTeam": "Équipe B",
                    "score": "2-1"
                }
            ]
        }
    ]
    
    Args:
        data: Données brutes de l'API
    
    Returns:
        Liste filtrée des résultats
    """
    output = []
    rounds = data.get("rounds", [])
    
    for round_item in rounds:
        # Filtrage J38 : Exception métier, on ignore les résultats de la journée 38
        if round_item.get("roundNumber") == 38:
            continue
            
        clean_round = {
            "roundNumber": round_item.get("roundNumber"),
            "matches": []
        }
        
        for match in round_item.get("matches", []):
            clean_match = {
                "id": match.get("id"),
                "homeTeam": match.get("homeTeam", {}).get("name"),
                "awayTeam": match.get("awayTeam", {}).get("name"),
                "score": match.get("score"),
            }
            
            clean_round["matches"].append(clean_match)
        
        output.append(clean_round)
    
    return output


def get_filtered_results(skip: int = 0, take: int = 5) -> List[Dict]:
    """
    Récupère et filtre les résultats en une seule fonction
    
    Args:
        skip: Nombre de résultats à sauter
        take: Nombre de résultats à récupérer
    
    Returns:
        Résultats filtrés
    """
    params = {"skip": skip, "take": take}
    
    try:
        response = requests.get(URL_RESULTS, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        
        raw_data = response.json()
        return extract_results_minimal(raw_data)
    
    except requests.exceptions.RequestException as e:
        print(f"[ERREUR] Impossible de recuperer les resultats : {e}")
        return []


# ==================== TEST ====================

if __name__ == "__main__":
    print("[TEST] Module Results Filter")
    print("=" * 60)
    
    # Test avec l'API directement
    print("\n[TEST 1] Recuperation et filtrage des resultats...")
    clean_data = get_filtered_results(skip=0, take=4)
    
    if clean_data:
        print(f"[OK] {len(clean_data)} journees filtrees")
        
        # Afficher un exemple
        if clean_data[0]["matches"]:
            example = clean_data[0]["matches"][0]
            print(f"[EXEMPLE] {example['homeTeam']} vs {example['awayTeam']} : {example['score']}")
        
        # Sauvegarder pour vérification
        with open("test_results_filtered.json", 'w', encoding='utf-8') as f:
            json.dump(clean_data, f, indent=2, ensure_ascii=False)
        print("[SAVED] Fichier test_results_filtered.json cree")
        
        # Statistiques de compression
        raw_response = requests.get(URL_RESULTS, headers=HEADERS, params={"skip": 0, "take": 4}, timeout=10)
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
