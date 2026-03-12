import unittest
import sys
import os
from pathlib import Path

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.zeus.utils.risk_manager import RiskManager

class TestZeusRiskManagement(unittest.TestCase):
    
    def setUp(self):
        self.initial_capital = 20000
        self.rm = RiskManager(self.initial_capital)
        
    def test_minimum_bet_rejection(self):
        """Vérifie que les paris inférieurs à 1000Ar sont rejetés."""
        # Cas 1: Mise de 500 Ar (doit être rejetée)
        est_valide, montant, msg = self.rm.valider_mise(500)
        self.assertFalse(est_valide)
        self.assertEqual(montant, 0)
        self.assertIn("inférieur au minimum", msg)
        
        # Cas 2: Mise de 1000 Ar (doit être acceptée)
        est_valide, montant, msg = self.rm.valider_mise(1000)
        self.assertTrue(est_valide)
        self.assertEqual(montant, 1000)
        
    def test_insufficient_bankroll_blocking(self):
        """Vérifie que le système bloque les mises excédant le bankroll disponible."""
        # Avec 20 000 Ar, on doit garder 1000 Ar. Max possible = 19 000 Ar.
        est_valide, montant, msg = self.rm.valider_mise(19500)
        self.assertFalse(est_valide)
        self.assertEqual(montant, 19000) # Plafonné au max possible
        self.assertIn("excède la limite de risque", msg)
        
        # Mise totalement impossible (si bankroll était déjà bas)
        self.rm.mettre_a_jour_capital(1500)
        # Max possible = 1500 - 1000 = 500. Mais 500 < MISE_MIN (1000).
        est_valide, montant, msg = self.rm.valider_mise(1000)
        self.assertFalse(est_valide)
        self.assertEqual(montant, 0)
        self.assertIn("Bankroll insuffisant", msg)
        
    def test_accuracy_after_multiple_operations(self):
        """Vérifie la précision des calculs après plusieurs opérations."""
        # Opération 1: Pari de 2000 Ar gagné avec cote 2.0 (+2000)
        self.rm.mettre_a_jour_capital(22000)
        self.assertEqual(self.rm.capital_actuel, 22000)
        
        # Opération 2: Pari de 5000 Ar perdu (-5000)
        self.rm.mettre_a_jour_capital(17000)
        self.assertEqual(self.rm.capital_actuel, 17000)
        
        # Vérification du max possible après ces opérations
        # 17000 - 1000 = 16000
        self.assertEqual(self.rm.calculer_mise_maximale(), 16000)
        
    def test_bankruptcy_risk_prevention(self):
        """Vérifie que le programme prévient automatiquement les risques de faillite."""
        # Simuler une chute du capital
        self.rm.mettre_a_jour_capital(6000) # Encore OK (> 5000)
        self.assertEqual(len(self.rm.alertes), 0)
        
        self.rm.mettre_a_jour_capital(4500) # Devrait déclencher une alerte
        self.assertEqual(len(self.rm.alertes), 1)
        self.assertIn("Bankroll critique", self.rm.alertes[0])
        
        # Vérifier le rapport de risque
        rapport = self.rm.generer_rapport_risque()
        self.assertEqual(rapport["niveau_risque"], "ÉLEVÉ")
        self.assertEqual(rapport["nb_alertes"], 1)
        
        # Vérifier blocage final
        self.rm.mettre_a_jour_capital(1050)
        est_valide, montant, msg = self.rm.valider_mise(1000)
        self.assertFalse(est_valide)
        self.assertEqual(montant, 0)

if __name__ == '__main__':
    unittest.main()
