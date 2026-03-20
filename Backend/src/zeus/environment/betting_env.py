import gymnasium as gym
from gymnasium import spaces
import numpy as np
import random
from .observation import construire_observation
from .reward import calculer_recompense, determiner_resultat
from ..utils.risk_manager import RiskManager
from ...core.database import get_db_connection
from typing import Dict, List, Tuple, Optional

# Espace d'actions basé sur des montants fixes (en Ariary).
# 0 = aucun pari, les autres actions sont des combinaisons
#   - type de pari : 1 / N / 2
#   - mise fixe : 1000, 1500, 2000, 2500 Ar
ACTION_SPACE_CONFIG = {
    0: {'type': 'Aucun', 'montant_ar': 0},
    1: {'type': '1', 'montant_ar': 1000},
    2: {'type': 'N', 'montant_ar': 1000},
    3: {'type': '2', 'montant_ar': 1000},
    4: {'type': '1', 'montant_ar': 1500},
    5: {'type': 'N', 'montant_ar': 1500},
    6: {'type': '2', 'montant_ar': 1500},
    7: {'type': '1', 'montant_ar': 2000},
    8: {'type': 'N', 'montant_ar': 2000},
    9: {'type': '2', 'montant_ar': 2000},
    10: {'type': '1', 'montant_ar': 2500},
    11: {'type': 'N', 'montant_ar': 2500},
    12: {'type': '2', 'montant_ar': 2500},
}
class BettingEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(
        self,
        capital_initial: int = 20000,
        journee_debut: int = 1,
        journee_fin: int = 38,
        mode: str = 'train',
        version_ia: str = 'v1.0',
        feature_session_id: Optional[int] = None
    ):
        super().__init__()
        self.capital_initial = capital_initial
        self.journee_debut = journee_debut
        self.journee_fin = journee_fin
        self.mode = mode
        self.version_ia = version_ia
        self.observation_space = spaces.Box(
            low=0.0,
            high=1.0,
            shape=(8,),
            dtype=np.float32
        )
        # 13 actions discrètes basées sur des montants fixes.
        self.action_space = spaces.Discrete(len(ACTION_SPACE_CONFIG))
        self.capital = capital_initial
        self.score_zeus = 0
        self.journee_actuelle = journee_debut
        self.matches_restants: List[Dict] = []
        self.match_actuel: Optional[Dict] = None
        self.session_id: Optional[int] = None
        self.session_id: Optional[int] = None
        self.conn = None
        self.risk_manager = RiskManager(capital_initial)
        self.historique_capital = []
        self.total_paris = 0
        self.paris_gagnants = 0
        self.feature_session_id = feature_session_id

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict] = None
    ) -> Tuple[np.ndarray, Dict]:
        super().reset(seed=seed)
        self.capital = self.capital_initial
        self.risk_manager = RiskManager(self.capital_initial)
        self.score_zeus = 0
        self.journee_actuelle = self.journee_debut
        self.historique_capital = [self.capital]
        self.total_paris = 0
        self.paris_gagnants = 0
        if self.conn is None:
            # On utilise get_db_connection qui gère déjà PostgreSQL via .env
            self.conn_context = get_db_connection(write=(self.mode == 'train'))
            self.conn = self.conn_context.__enter__()

        # En mode entraînement, on crée une session en base.
        if self.mode == 'train':
            from ..database.queries import create_session
            type_session = 'TRAINING'
            self.session_id = create_session(
                self.capital_initial,
                type_session,
                self.version_ia,
                self.conn
            )
        else:
            self.session_id = None
        self._charger_matches()
        if len(self.matches_restants) > 0:
            self.match_actuel = self.matches_restants.pop(0)
        else:
            raise ValueError("Aucun match disponible pour cet épisode")
        observation = self._get_observation()
        info = self._get_info()
        return observation, info
    def _charger_matches(self):
        from ..database.queries import get_matches_for_journee
        all_matches = []
        for journee in range(self.journee_debut, self.journee_fin + 1):
            matches = get_matches_for_journee(
                journee,
                self.conn,
                session_id=self.feature_session_id
            )
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
        if self.match_actuel is None:
            return np.zeros(8, dtype=np.float32)
        return construire_observation(
            self.match_actuel['equipe_dom_id'],
            self.match_actuel['equipe_ext_id'],
            self.match_actuel['journee'],
            self.match_actuel['cote_1'],
            self.match_actuel['cote_x'],
            self.match_actuel['cote_2'],
            self.conn,
            self.feature_session_id
        )
    def _get_info(self) -> Dict:
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
        if self.match_actuel is None:
            raise RuntimeError("Pas de match actuel. Appelez reset() d'abord.")

        if action not in ACTION_SPACE_CONFIG:
            raise ValueError(f"Action invalide pour ZEUS : {action}")

        action_config = ACTION_SPACE_CONFIG[action]
        type_pari = action_config['type']
        montant_ar = action_config['montant_ar']

        est_valide, mise_finale, _ = self.risk_manager.valider_mise(montant_ar)
        if not est_valide:
            mise_finale = 0
            type_pari = 'Aucun'
        if type_pari == '1':
            cote_jouee = float(self.match_actuel['cote_1']) if self.match_actuel['cote_1'] is not None else None
        elif type_pari == 'N':
            cote_jouee = float(self.match_actuel['cote_x']) if self.match_actuel['cote_x'] is not None else None
        elif type_pari == '2':
            cote_jouee = float(self.match_actuel['cote_2']) if self.match_actuel['cote_2'] is not None else None
        else:
            cote_jouee = None
        prob_implicite = 1.0 / cote_jouee if cote_jouee and cote_jouee > 0 else None
        pourcentage_reel = (mise_finale / self.capital) if self.capital > 0 else 0
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
        if pari_gagne is True:
            profit_net = int(mise_finale * (cote_jouee - 1))
            self.capital += profit_net
        elif pari_gagne is False:
            profit_net = -mise_finale
            self.capital += profit_net  
        else:
            profit_net = 0
        self.risk_manager.mettre_a_jour_capital(self.capital)
        reward, self.score_zeus = calculer_recompense(
            mise_finale,
            cote_jouee,
            pari_gagne,
            self.capital,
            self.score_zeus
        )

        # En évaluation, on n'écrit pas dans l'historique pour éviter les verrous.
        if self.session_id is not None:
            from ..database.queries import enregistrer_pari
            enregistrer_pari(
                session_id=self.session_id,
                prediction_id=self.match_actuel['id'],
                journee=self.match_actuel['journee'],
                type_pari=type_pari,
                mise_ar=int(mise_finale),
                pourcentage_bankroll=float(pourcentage_reel),
                cote_jouee=float(cote_jouee) if cote_jouee else None,
                resultat=1 if pari_gagne is True else (0 if pari_gagne is False else None),
                profit_net=int(profit_net),
                bankroll_apres=int(self.capital),
                probabilite_implicite=float(prob_implicite) if prob_implicite else None,
                action_id=int(action),
                conn=self.conn
            )
        self.historique_capital.append(self.capital)
        terminated = False
        truncated = False
        if self.capital < 1000:
            terminated = True
        if len(self.matches_restants) > 0:
            self.match_actuel = self.matches_restants.pop(0)
        else:
            terminated = True
            if self.session_id is not None:
                from ..database.queries import finaliser_session
                profit_total = self.capital - self.capital_initial
                finaliser_session(
                    self.session_id,
                    self.capital,
                    profit_total,
                    self.score_zeus,
                    self.conn
                )
                self.conn.commit()
        next_observation = self._get_observation()
        info = self._get_info()
        return next_observation, reward, terminated, truncated, info
    def close(self):
        if self.conn is not None:
            self.conn_context.__exit__(None, None, None)
            self.conn = None
