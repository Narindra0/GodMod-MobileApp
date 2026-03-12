
import unittest
import os
import sqlite3
import sys

# Ajouter la racine du projet au PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import session_manager
from src.core import database
from src.core import config

class TestSessionManager(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Utiliser une base de données de test avec chemin absolu
        cls.test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        if not os.path.exists(cls.test_dir):
            os.makedirs(cls.test_dir)
        cls.test_db = os.path.join(cls.test_dir, "test_godmod.db")
        config.DB_NAME = cls.test_db
        if os.path.exists(cls.test_db):
            os.remove(cls.test_db)
        database.initialiser_db()

    def test_01_create_initial_session(self):
        """Vérifie la création de la première session."""
        session = session_manager.get_active_session()
        self.assertIsNotNone(session)
        self.assertEqual(session['current_day'], 1)
        self.assertEqual(session['capital_initial'], 20000)
        
    def test_02_update_day(self):
        """Vérifie l'incrémentation du jour."""
        session = session_manager.get_active_session()
        updated = session_manager.update_session_day(session['id'], 5)
        self.assertEqual(updated['current_day'], 5)
        
        # Vérifier en DB
        with database.get_db_connection() as conn:
            row = conn.execute("SELECT current_day FROM sessions WHERE id = ?", (session['id'],)).fetchone()
            self.assertEqual(row[0], 5)

    def test_03_transition_after_37(self):
        """Vérifie le basculement automatique après le jour 37."""
        session_v1 = session_manager.get_active_session()
        id_v1 = session_v1['id']
        
        # Simuler le passage au jour 38 (déclenche la transition)
        session_v2 = session_manager.update_session_day(id_v1, 38)
        
        self.assertNotEqual(id_v1, session_v2['id'])
        self.assertEqual(session_v2['current_day'], 1)
        
        # Vérifier que l'ancienne est fermée
        with database.get_db_connection() as conn:
            status = conn.execute("SELECT status FROM sessions WHERE id = ?", (id_v1,)).fetchone()[0]
            self.assertEqual(status, 'CLOSED')

    def test_04_capital_persistence(self):
        """Vérifie que le capital est transmis entre sessions."""
        session_v2 = session_manager.get_active_session()
        id_v2 = session_v2['id']
        
        # Simuler un pari gagnant pour changer le bankroll
        with database.get_db_connection() as conn:
            # Créer un match et une prédiction bidon pour FK
            conn.execute("INSERT INTO matches (session_id, journee, equipe_dom_id, equipe_ext_id) VALUES (?, 1, 1, 2)", (id_v2,))
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO predictions (session_id, match_id, prediction) VALUES (?, ?, '1')", (id_v2, mid))
            pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            # Insérer un pari final
            conn.execute("""
                INSERT INTO historique_paris (session_id, prediction_id, bankroll_apres) 
                VALUES (?, ?, 25000)
            """, (id_v2, pid))
            conn.commit()
            
        # Forcer transition
        session_v3 = session_manager.create_new_session()
        self.assertEqual(session_v3['capital_initial'], 25000)

if __name__ == '__main__':
    unittest.main()
