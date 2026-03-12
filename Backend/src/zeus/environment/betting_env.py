"""
Environnement Gymnasium pour l'agent ZEUS.
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import sqlite3
from typing import Dict, List, Optional, Tuple, Any
import random

from ..database.queries import (
    get_matches_for_journee,
    get_match_data,
    create_session,
    enregistrer_pari,
    finaliser_session
)
from .observation import construire_observation
from .reward import calculer_recompense, determiner_resultat
from ..utils.risk_manager import RiskManager


# Configuration des actions (MISES FIXES EN Ar)
# Action 0: Abstention
# Actions 1-6: Paris PRUDENTS (1000-1500 Ar)
# Actions 7-12: Paris CONVICTION (2000-2500 Ar)
ACTION_SPACE_CONFIG = {
    0: {'type': 'Aucun', 'montant_ar': 0},
    
    # PRUDENCE sur 1, N, 2 (1000 Ar)
    1: {'type': '1', 'montant_ar': 1000},
    2: {'type': 'N', 'montant_ar': 1000},
    3: {'type': '2', 'montant_ar': 1000},
    
    # PRUDENCE+ sur 1, N, 2 (1500 Ar)
    4: {'type': '1', 'montant_ar': 1500},
    5: {'type': 'N', 'montant_ar': 1500},
    6: {'type': '2', 'montant_ar': 1500},
    
    # CONVICTION sur 1, N, 2 (2000 Ar)
    7: {'type': '1', 'montant_ar': 2000},
    8: {'type': 'N', 'montant_ar': 2000},
    9: {'type': '2', 'montant_ar': 2000},
    
    # CONVICTION+ sur 1, N, 2 (2500 Ar)
    10: {'type': '1', 'montant_ar': 2500},
    11: {'type': 'N', 'montant_ar': 2500},
    12: {'type': '2', 'montant_ar': 2500},
}


class BettingEnv(gym.Env):
    """
    Environnement Gymnasium pour paris sportifs avec apprentissage par renforcement.
    
    Observation Space: Box(8,) normalisé [0, 1]
    Action Space: Discrete(13) - Abstention + 12 types de paris
    """
    
    metadata = {'render_modes': []}
    
    def __init__(
        self,
        db_path: str,
        capital_initial: int = 20000,
        journee_debut: int = 1,
        journee_fin: int = 38,
        mode: str = 'train',
        version_ia: str = 'v1.0'
    ):
        """
        Args:
            db_path: Chemin vers la base SQLite
            capital_initial: Capital de départ (20000 Ar)
            journee_debut: Première journée de l'épisode
            journee_fin: Dernière journée de l'épisode
            mode: 'train' ou 'eval'
            version_ia: Version du modèle pour tracking
        """
        super().__init__()
        
        self.db_path = db_path
        self.capital_initial = capital_initial
        self.journee_debut = journee_debut
        self.journee_fin = journee_fin
        self.mode = mode
        self.version_ia = version_ia
        
        # Espaces Gymnasium
        self.observation_space = spaces.Box(
            low=0.0,
            high=1.0,
            shape=(8,),
            dtype=np.float32
        )
        self.action_space = spaces.Discrete(13)
        
        # État interne
        self.capital = capital_initial
        self.score_zeus = 0
        self.journee_actuelle = journee_debut
        self.matches_restants: List[Dict] = []
        self.match_actuel: Optional[Dict] = None
        self.session_id: Optional[int] = None
        self.conn: Optional[sqlite3.Connection] = None
        
        # Gestionnaire de risques
        self.risk_manager = RiskManager(capital_initial)
        
        # Historique pour métriques
        self.historique_capital = []
        self.total_paris = 0
        self.paris_gagnants = 0
        
    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict] = None
    ) -> Tuple[np.ndarray, Dict]:
        """
        Réinitialise l'environnement pour un nouvel épisode.
        
        Returns:
            Tuple (observation, info)
        """
        super().reset(seed=seed)
        
        # Réinitialiser l'état
        self.capital = self.capital_initial
        self.risk_manager = RiskManager(self.capital_initial)
        self.score_zeus = 0
        self.journee_actuelle = self.journee_debut
        self.historique_capital = [self.capital]
        self.total_paris = 0
        self.paris_gagnants = 0
        
        # Connexion DB
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        
        # Créer session de tracking
        type_session = 'TRAINING' if self.mode == 'train' else 'EVALUATION'
        self.session_id = create_session(
            self.capital_initial,
            type_session,
            self.version_ia,
            self.conn
        )
        
        # Charger tous les matchs de l'épisode
        self._charger_matches()
        
        # Charger le premier match
        if len(self.matches_restants) > 0:
            self.match_actuel = self.matches_restants.pop(0)
        else:
            raise ValueError("Aucun match disponible pour cet épisode")
        
        # Générer observation
        observation = self._get_observation()
        info = self._get_info()
        
        return observation, info
    
    def _charger_matches(self):
        """Charge tous les matchs TERMINE de la plage de journées avec cotes valides."""
        all_matches = []
        for journee in range(self.journee_debut, self.journee_fin + 1):
            matches = get_matches_for_journee(journee, self.conn)
            # Ne garder que les matchs TERMINES avec des cotes valides
            matches_valides = [
                m for m in matches 
                if m['status'] == 'TERMINE' 
                and m['cote_1'] is not None 
                and m['cote_x'] is not None 
                and m['cote_2'] is not None
            ]
            all_matches.extend(matches_valides)
        
        self.matches_restants = all_matches
        
        if len(all_matches) == 0:
            raise ValueError(
                f"Aucun match TERMINE trouvé entre J{self.journee_debut} "
                f"et J{self.journee_fin}"
            )
    
    def _get_observation(self) -> np.ndarray:
        """Construit le vecteur d'observation pour le match actuel."""
        if self.match_actuel is None:
            # Observation par défaut si pas de match
            return np.zeros(8, dtype=np.float32)
        
        return construire_observation(
            self.match_actuel['equipe_dom_id'],
            self.match_actuel['equipe_ext_id'],
            self.match_actuel['journee'],
            self.match_actuel['cote_1'],
            self.match_actuel['cote_x'],
            self.match_actuel['cote_2'],
            self.conn
        )
    
    def _get_info(self) -> Dict:
        """Retourne des infos de debug."""
        return {
            'capital': self.capital,
            'score_zeus': self.score_zeus,
            'journee': self.match_actuel['journee'] if self.match_actuel else 0,
            'matches_restants': len(self.matches_restants),
            'total_paris': self.total_paris,
            'paris_gagnants': self.paris_gagnants,
            'win_rate': self.paris_gagnants / max(self.total_paris, 1)
        }
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Exécute une action et retourne le résultat.
        
        Args:
            action: ID de l'action (0-12)
            
        Returns:
            Tuple (observation, reward, terminated, truncated, info)
        """
        if self.match_actuel is None:
            raise RuntimeError("Pas de match actuel. Appelez reset() d'abord.")
        
        # Récupérer config de l'action
        action_config = ACTION_SPACE_CONFIG[action]
        type_pari = action_config['type']
        montant_ar = action_config['montant_ar']
        
        # Validation via le RiskManager
        est_valide, mise_finale, msg_risk = self.risk_manager.valider_mise(montant_ar)
        
        if not est_valide:
            # Si la mise est invalide (trop faible ou bankroll insuffisant)
            # On force l'abstention pour éviter la faillite immédiate non désirée
            mise_finale = 0
            type_pari = 'Aucun'
        
        # Récupérer la cote jouée
        if type_pari == '1':
            cote_jouee = self.match_actuel['cote_1']
        elif type_pari == 'N':
            cote_jouee = self.match_actuel['cote_x']
        elif type_pari == '2':
            cote_jouee = self.match_actuel['cote_2']
        else:
            cote_jouee = None
        
        # Calculer probabilité implicite
        prob_implicite = 1.0 / cote_jouee if cote_jouee and cote_jouee > 0 else None
        
        # Calculer le pourcentage réel pour la DB (legacy)
        pourcentage_reel = (mise_finale / self.capital) if self.capital > 0 else 0
        
        # Déterminer le résultat du pari
        if type_pari != 'Aucun':
            pari_gagne = determiner_resultat(
                type_pari,
                self.match_actuel['score_dom'],
                self.match_actuel['score_ext']
            )
            self.total_paris += 1
            if pari_gagne:
                self.paris_gagnants += 1
        else:
            pari_gagne = None
        
        # Calculer profit/perte
        if pari_gagne is True:
            profit_net = int(mise_finale * (cote_jouee - 1))
            self.capital += profit_net
        elif pari_gagne is False:
            profit_net = -mise_finale
            self.capital += profit_net  # Soustraction car profit_net est négatif
        else:
            profit_net = 0
        
        # Mettre à jour le RiskManager
        self.risk_manager.mettre_a_jour_capital(self.capital)
        
        # Calculer la récompense RL
        reward, self.score_zeus = calculer_recompense(
            mise_finale,
            cote_jouee,
            pari_gagne,
            self.capital,
            self.score_zeus
        )
        
        # Enregistrer dans l'historique
        enregistrer_pari(
            session_id=self.session_id,
            prediction_id=self.match_actuel['id'], # Ici prediction_id = match_id par simplicité
            journee=self.match_actuel['journee'],
            type_pari=type_pari,
            mise_ar=mise_finale,
            pourcentage_bankroll=pourcentage_reel,
            cote_jouee=cote_jouee,
            resultat=1 if pari_gagne is True else (0 if pari_gagne is False else None),
            profit_net=profit_net,
            bankroll_apres=self.capital,
            probabilite_implicite=prob_implicite,
            action_id=action,
            conn=self.conn
        )
        
        self.historique_capital.append(self.capital)
        
        # Vérifier conditions de terminaison
        terminated = False
        truncated = False
        
        # Banqueroute
        if self.capital < 1000:
            terminated = True
        
        # Charger le prochain match
        if len(self.matches_restants) > 0:
            self.match_actuel = self.matches_restants.pop(0)
        else:
            # Fin de saison
            terminated = True
            
            # Finaliser la session
            profit_total = self.capital - self.capital_initial
            finaliser_session(
                self.session_id,
                self.capital,
                profit_total,
                self.score_zeus,
                self.conn
            )
        
        # Nouvelle observation
        next_observation = self._get_observation()
        info = self._get_info()
        
        return next_observation, reward, terminated, truncated, info
    
    def close(self):
        """Ferme la connexion DB."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None
