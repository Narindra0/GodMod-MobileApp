from typing import Dict, List


def extract_matches_with_local_ids(data: Dict, limit: int = 1) -> List[Dict]:
    rounds_raw = data.get("rounds", [])
    rounds_valid = [r for r in rounds_raw if r.get("roundNumber") != 38]
    rounds = sorted(rounds_valid, key=lambda r: r.get("roundNumber", 0))[:limit]
    output = []
    for r in rounds:
        clean_round = {"roundNumber": r.get("roundNumber"), "expectedStart": r.get("expectedStart"), "matches": []}
        for local_id, m in enumerate(r.get("matches", []), start=1):
            odds = []
            for bet_type in m.get("eventBetTypes", []):
                if bet_type.get("name") == "1X2":
                    for item in bet_type.get("eventBetTypeItems", []):
                        odds.append({"type": item.get("shortName"), "odds": item.get("odds")})
            clean_match = {
                "matchId": local_id,
                "name": m.get("name"),
                "homeTeam": m.get("homeTeam", {}).get("name"),
                "awayTeam": m.get("awayTeam", {}).get("name"),
                "round": str(r.get("roundNumber")),
                "odds": odds,
            }
            clean_round["matches"].append(clean_match)
        output.append(clean_round)
    return output
