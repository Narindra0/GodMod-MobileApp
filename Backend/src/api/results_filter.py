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
        return []
