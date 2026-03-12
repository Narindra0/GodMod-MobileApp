"""
Module de communication avec l'API interne du site
Remplace le scraping HTML par des appels API directs

Version: 2.1
Date: Janvier 2025
"""

import requests
import json
from typing import List, Dict, Optional

# ==================== CONFIGURATION ====================

# Headers HTTP cruciaux pour ne pas être bloqué (Erreur 403)
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr",
    "App-Version": "31358",  # ⚠️ À surveiller si le site se met à jour
    "Origin": "https://bet261.mg",
    "Referer": "https://bet261.mg/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site"
}

BASE_URL = "https://hg-event-api-prod.sporty-tech.net/api"
LEAGUE_ID = 8035  # ID de la ligue par défaut

# URLs spécifiques (pour compatibilité avec les filtres)
URL_RANKING = f"{BASE_URL}/instantleagues/{LEAGUE_ID}/ranking"
URL_RESULTS = f"{BASE_URL}/instantleagues/{LEAGUE_ID}/results"
URL_MATCHS = f"{BASE_URL}/instantleagues/{LEAGUE_ID}/matches"

# ==================== FONCTIONS API ====================

def get_ranking(league_id: int = LEAGUE_ID) -> List[Dict]:
    """
    Récupère le classement complet de la ligue en JSON
    """
    url = f"{BASE_URL}/instantleagues/{league_id}/ranking"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        # Gestion specifique 502/503 (Maintenance)
        if response.status_code in [502, 503, 504]:
            print(f"⚠️ API en Maintenance (Code {response.status_code})")
            return []
            
        response.raise_for_status() 
        data = response.json()
        return data.get("teams", [])
    
    except requests.exceptions.Timeout:
        print(f"⏱️ Timeout API Ranking (>15s)")
        return []
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur API Ranking : {e}")
        return []

def get_recent_results(league_id: int = LEAGUE_ID, skip: int = 0, take: int = 5) -> Dict:
    """
    Récupère les résultats récents de la ligue
    """
    url = f"{BASE_URL}/instantleagues/{league_id}/results"
    params = {"skip": skip, "take": take}
    
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        
        if response.status_code in [502, 503, 504]:
            return {"rounds": []}
            
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur API Results : {e}")
        return {"rounds": []}

def get_upcoming_matches(league_id: int = LEAGUE_ID) -> Dict:
    """
    Récupère les matchs à venir de la ligue
    """
    url = f"{BASE_URL}/instantleagues/{league_id}/matches"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        
        if response.status_code in [502, 503, 504]:
            return {"rounds": []}
            
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur API Matches : {e}")
        return {"rounds": []}


# ==================== UTILITAIRES ====================

def save_to_json(data: Dict, filename: str):
    """Sauvegarde les données dans un fichier JSON"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[SAVED] Donnees sauvegardees dans {filename}")


# ==================== TESTS ====================

if __name__ == "__main__":
    print("[TEST] Module API Client")
    print("")
    print("=" * 60)
    
    # Test 1: Classement
    print("\n[TEST 1] Recuperation du classement...")
    ranking = get_ranking()
    if ranking:
        print(f"   [OK] {len(ranking)} equipes recuperees")
        print(f"   [DATA] Exemple - 1ere equipe FULL: {ranking[0]}")
        # print(f"   [DATA] Exemple - 1ere equipe: {ranking[0].get('name', 'N/A')}")
        save_to_json({"teams": ranking}, "test_ranking.json")
    else:
        print("   ❌ Échec de la récupération")
    
    # Test 2: Résultats
    print("\n[TEST 2] Recuperation des resultats...")
    results = get_recent_results(take=3)
    rounds = results.get('rounds', [])
    if rounds:
        print(f"   [OK] {len(rounds)} journees recuperees")
        if rounds[0].get('matches'):
            first_match = rounds[0]['matches'][0]
            print(f"   [MATCH] Exemple: {first_match.get('homeTeam', {}).get('name')} vs {first_match.get('awayTeam', {}).get('name')}")
        save_to_json(results, "test_results.json")
    else:
        print("   ❌ Échec de la récupération")
    
    # Test 3: Matchs à venir
    print("\n[TEST 3] Recuperation des matchs a venir...")
    matches = get_upcoming_matches()
    match_rounds = matches.get('rounds', [])
    if match_rounds:
        print(f"   [OK] {len(match_rounds)} journees a venir")
        if match_rounds[0].get('matches'):
            upcoming = match_rounds[0]['matches'][0]
            print(f"   [NEXT] Prochain: {upcoming.get('homeTeam', {}).get('name')} vs {upcoming.get('awayTeam', {}).get('name')}")
        save_to_json(matches, "test_matches.json")
    else:
        print("   ❌ Échec de la récupération")
    
    print("\n" + "=" * 60)
    print("[SUCCESS] Tests termines ! Verifiez les fichiers JSON generes.")
