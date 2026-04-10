"""
Tests unitaires pour session_manager.py
Fichier critique - tous les autres modules dépendent d'une session valide.
"""
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ajouter le dossier src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core import session_manager
from core import config


class TestSessionManager(unittest.TestCase):
    """Tests pour les fonctions de gestion des sessions."""

    def setUp(self):
        """Configuration avant chaque test."""
        self.mock_cursor = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor

    # ==========================================================================
    # Scénario 1 — Création d'une nouvelle session
    # ==========================================================================
    def test_create_new_session_returns_valid_session(self):
        """
        Vérifier qu'une nouvelle session créée a :
        - un id valide (non None)
        - un capital_initial = config.DEFAULT_BANKROLL
        - un current_day qui commence à 1
        """
        # Simuler : pas de session active existante
        self.mock_cursor.fetchone.side_effect = [
            None,  # Pas de session active
            {"id": 42},  # Nouvelle session créée avec id=42
        ]

        result = session_manager._create_new_session_internal(self.mock_conn)

        self.assertIsNotNone(result["id"])
        self.assertEqual(result["capital_initial"], config.DEFAULT_BANKROLL)
        self.assertEqual(result["current_day"], 1)

    def test_create_new_session_inherits_prisma_score(self):
        """
        Vérifier que la nouvelle session hérite du score_prisma de l'ancienne session.
        """
        # Simuler : session active existante avec score_prisma=350
        self.mock_cursor.fetchone.side_effect = [
            {"id": 10, "capital_initial": 25000, "score_prisma": 350},  # Session active
            {"bankroll_apres": 28000},  # Dernier bankroll
            {"id": 42},  # Nouvelle session
        ]

        result = session_manager._create_new_session_internal(self.mock_conn)

        # Le score_prisma doit être hérité
        self.assertEqual(result["score_prisma"], 350)

    # ==========================================================================
    # Scénario 2 — Transition automatique quand day_number > SESSION_MAX_DAYS
    # ==========================================================================
    def test_update_session_day_creates_new_session_when_limit_reached(self):
        """
        Vérifier qu'une NOUVELLE session est créée quand day_number > SESSION_MAX_DAYS.
        """
        # Simuler la création d'une nouvelle session
        with patch.object(session_manager, 'create_new_session') as mock_create:
            mock_create.return_value = {
                "id": 999,
                "current_day": 1,
                "capital_initial": config.DEFAULT_BANKROLL,
            }

            # Appeler avec un jour au-delà de la limite
            day_limit = config.SESSION_MAX_DAYS + 1
            result = session_manager.update_session_day(123, day_limit)

            # La fonction create_new_session doit avoir été appelée
            mock_create.assert_called_once()
            # Le résultat doit être la nouvelle session
            self.assertEqual(result["id"], 999)
            self.assertEqual(result["current_day"], 1)

    def test_update_session_day_updates_existing_session_when_within_limit(self):
        """
        Vérifier que la session existante est mise à jour quand dans la limite.
        """
        # Simuler la mise à jour
        self.mock_cursor.rowcount = 1

        result = session_manager._update_session_day_internal(
            self.mock_conn, 123, 10
        )

        self.assertEqual(result["id"], 123)
        self.assertEqual(result["current_day"], 10)
        # Vérifier que UPDATE a été appelé
        self.mock_cursor.execute.assert_called()

    # ==========================================================================
    # Scénario 3 — Récupération de la session active
    # ==========================================================================
    def test_get_active_session_creates_new_if_none_exists(self):
        """
        Vérifier qu'une session est créée automatiquement si la base est vide.
        """
        # Simuler : pas de session active
        self.mock_cursor.fetchone.side_effect = [
            None,  # Pas de session active
            {"id": 42},  # Nouvelle session créée
        ]

        result = session_manager._get_active_session_internal(self.mock_conn)

        self.assertIn("id", result)
        self.assertIn("current_day", result)
        self.assertIn("capital_initial", result)
        self.assertIsNotNone(result["id"])

    def test_get_active_session_returns_existing_session(self):
        """
        Vérifier qu'on récupère la session active existante.
        """
        # Simuler : session active existante
        self.mock_cursor.fetchone.return_value = {
            "id": 42,
            "current_day": 15,
            "capital_initial": 25000,
        }

        result = session_manager._get_active_session_internal(self.mock_conn)

        self.assertEqual(result["id"], 42)
        self.assertEqual(result["current_day"], 15)
        self.assertEqual(result["capital_initial"], 25000)


if __name__ == "__main__":
    unittest.main()
