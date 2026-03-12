
import unittest
from typing import Dict
from src.api.matches_filter import extract_matches_with_local_ids
from src.api.results_filter import extract_results_minimal

class TestJ38Exception(unittest.TestCase):
    """
    Test pour valider que la journée 38 est systématiquement ignorée par les filtres API.
    """

    def test_filter_j38_upcoming_matches(self):
        # Données fictives incluant J37 et J38
        fake_data = {
            "rounds": [
                {
                    "roundNumber": 37,
                    "matches": [{"id": "m37", "homeTeam": {"name": "Team A"}, "awayTeam": {"name": "Team B"}, "eventBetTypes": []}]
                },
                {
                    "roundNumber": 38,
                    "matches": [{"id": "m38", "homeTeam": {"name": "Team C"}, "awayTeam": {"name": "Team D"}, "eventBetTypes": []}]
                }
            ]
        }
        
        # Extraction
        result = extract_matches_with_local_ids(fake_data, limit=10)
        
        # Vérification
        round_numbers = [r["roundNumber"] for r in result]
        self.assertIn(37, round_numbers)
        self.assertNotIn(38, round_numbers)
        print(f"✅ Test matches_filter J38 réussi. Rounds extraits : {round_numbers}")

    def test_filter_j38_results(self):
        # Données fictives incluant J37 et J38
        fake_data = {
            "rounds": [
                {
                    "roundNumber": 37,
                    "matches": [{"id": "m37", "homeTeam": {"name": "Team A"}, "awayTeam": {"name": "Team B"}, "score": "1:0"}]
                },
                {
                    "roundNumber": 38,
                    "matches": [{"id": "m38", "homeTeam": {"name": "Team C"}, "awayTeam": {"name": "Team D"}, "score": "2:2"}]
                }
            ]
        }
        
        # Extraction
        result = extract_results_minimal(fake_data)
        
        # Vérification
        round_numbers = [r["roundNumber"] for r in result]
        self.assertIn(37, round_numbers)
        self.assertNotIn(38, round_numbers)
        print(f"✅ Test results_filter J38 réussi. Rounds extraits : {round_numbers}")

if __name__ == "__main__":
    unittest.main()
