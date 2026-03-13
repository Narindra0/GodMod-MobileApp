"""
Module de communication avec l'API interne du site
Remplace le scraping HTML par des appels API directs

Version: 2.1
Date: Janvier 2025
"""

import time
import json
import requests
from typing import List, Dict

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr",
    "App-Version": "31358",
    "Origin": "https://bet261.mg",
    "Referer": "https://bet261.mg/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site"
}

BASE_URL = "https://hg-event-api-prod.sporty-tech.net/api"
LEAGUE_ID = 8035

URL_RANKING = f"{BASE_URL}/instantleagues/{LEAGUE_ID}/ranking"
URL_RESULTS = f"{BASE_URL}/instantleagues/{LEAGUE_ID}/results"
URL_MATCHS = f"{BASE_URL}/instantleagues/{LEAGUE_ID}/matches"


def _get_with_retry(url: str, *, params: Dict = None, timeout: int = 15, max_attempts: int = 3) -> requests.Response:
    """Effectue un GET avec retry et backoff exponentiel léger."""
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)


def get_ranking(league_id: int = LEAGUE_ID) -> List[Dict]:
    """
    Récupère le classement complet de la ligue en JSON
    """
    url = f"{BASE_URL}/instantleagues/{league_id}/ranking"
    
    try:
        response = _get_with_retry(url, timeout=15)
        
        if response.status_code in [502, 503, 504]:
            return []
            
        response.raise_for_status() 
        data = response.json()
        return data.get("teams", [])
    
    except requests.exceptions.Timeout:
        return []
    except requests.exceptions.RequestException as e:
        return []


def get_recent_results(league_id: int = LEAGUE_ID, skip: int = 0, take: int = 5) -> Dict:
    """
    Récupère les résultats récents de la ligue
    """
    url = f"{BASE_URL}/instantleagues/{league_id}/results"
    params = {"skip": skip, "take": take}
    
    try:
        response = _get_with_retry(url, params=params, timeout=15)
        
        if response.status_code in [502, 503, 504]:
            return {"rounds": []}
            
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        return {"rounds": []}


def get_upcoming_matches(league_id: int = LEAGUE_ID) -> Dict:
    """
    Récupère les matchs à venir de la ligue
    """
    url = f"{BASE_URL}/instantleagues/{league_id}/matches"
    
    try:
        response = _get_with_retry(url, timeout=15)
        
        if response.status_code in [502, 503, 504]:
            return {"rounds": []}
            
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        return {"rounds": []}


def save_to_json(data: Dict, filename: str):
    """Sauvegarde les données dans un fichier JSON"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
