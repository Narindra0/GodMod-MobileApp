from typing import Dict, List


def extract_results_minimal(data: Dict) -> List[Dict]:
    output = []
    rounds = data.get("rounds", [])
    for round_item in rounds:
        if round_item.get("roundNumber") == 38:
            continue
        clean_round = {"roundNumber": round_item.get("roundNumber"), "matches": []}
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
