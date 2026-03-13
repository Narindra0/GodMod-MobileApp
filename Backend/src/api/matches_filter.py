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

ROUND_LIMIT = 1

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
                    "matchId": 1,
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
    rounds_raw = data.get("rounds", [])
    rounds_valid = [r for r in rounds_raw if r.get("roundNumber") != 38]
    
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
        
        for local_id, m in enumerate(r.get("matches", []), start=1):
            odds = []
            
            for bet_type in m.get("eventBetTypes", []):
                if bet_type.get("name") == "1X2":
                    for item in bet_type.get("eventBetTypeItems", []):
                        odds.append({
                            "type": item.get("shortName"),
                            "odds": item.get("odds")
                        })
            
            clean_match = {
                "matchId": local_id,
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
        return []
