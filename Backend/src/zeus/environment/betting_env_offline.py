"""
BettingEnv Offline — Version CSV pour Google Colab.

Lit les matchs et le classement depuis des fichiers CSV pandas
au lieu de PostgreSQL. Zéro connexion à Neon pendant l'entraînement.

Usage dans Colab :
    env = BettingEnvOffline(
        matches_csv="matches_training.csv",
        classement_csv="classement_training.csv",
    )
"""
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from ..utils.rng_bias import BiasStats, DEFAULT_BIAS
from ..utils.risk_manager import RiskManager
from .reward import calculer_recompense, calculer_recompense_skip, determiner_resultat

# Espace d'action v2 (identique à betting_env.py)
ACTION_SPACE_CONFIG = {
    0: "Aucun",
    1: "1",
    2: "N",
    3: "2",
}

_CAPITAL_DEFAULT = 20000


class BettingEnvOffline(gym.Env):
    """
    Environnement ZEUS v2 fonctionnant entièrement depuis des CSV pandas.
    Compatible avec l'entraînement sur Google Colab sans connexion DB.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        matches_csv: str,
        classement_csv: str,
        capital_initial: int = _CAPITAL_DEFAULT,
        journee_debut: int = 1,
        journee_fin: int = 37,
        mode: str = "train",
        version_ia: str = "v2.0",
        feature_session_id: Optional[int] = None,
    ):
        super().__init__()
        self.capital_initial = capital_initial
        self.journee_debut = journee_debut
        self.journee_fin = journee_fin
        self.mode = mode
        self.version_ia = version_ia
        self.feature_session_id = feature_session_id

        # Espaces (identiques à BettingEnv)
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(14,), dtype=np.float32)
        self.action_space = spaces.Discrete(len(ACTION_SPACE_CONFIG))

        # Chargement des CSV (une seule fois à l'init)
        print(f"Chargement des données depuis CSV...")
        self._matches_df = pd.read_csv(matches_csv)
        self._classement_df = pd.read_csv(classement_csv)
        print(f"  ✅ {len(self._matches_df)} matchs | {len(self._classement_df)} lignes classement")

        # Calcul des biais RNG depuis les CSV (Pilier 1)
        self.bias_stats: BiasStats = self._calculer_biais_depuis_csv()
        print(f"  ✅ Biais RNG : {self.bias_stats}")

        # Construction du cache classement depuis le DataFrame
        self._classement_cache: Dict[Tuple[int, int], Dict] = self._construire_classement_cache()

        # État de l'épisode
        self.capital = capital_initial
        self.score_zeus = 0
        self.matches_restants: List[Dict] = []
        self.match_actuel: Optional[Dict] = None
        self.risk_manager = RiskManager(capital_initial)
        self.historique_capital: List[int] = []
        self.total_paris = 0
        self.paris_gagnants = 0

    def _calculer_biais_depuis_csv(self) -> BiasStats:
        """Calcule les biais RNG directement depuis le DataFrame matches."""
        df = self._matches_df
        df_termine = df[
            (df["status"] == "TERMINE")
            & df["cote_1"].notna()
            & df["cote_x"].notna()
            & df["cote_2"].notna()
            & df["score_dom"].notna()
            & df["score_ext"].notna()
        ].copy()

        total = len(df_termine)
        if total < 50:
            print(f"  ⚠️ Données insuffisantes ({total} matchs) → utilisation des valeurs par défaut")
            return DEFAULT_BIAS

        taux_1 = (df_termine["score_dom"] > df_termine["score_ext"]).mean()
        taux_N = (df_termine["score_dom"] == df_termine["score_ext"]).mean()
        taux_2 = (df_termine["score_dom"] < df_termine["score_ext"]).mean()

        prob_impl_1 = (1.0 / df_termine["cote_1"]).mean()
        prob_impl_N = (1.0 / df_termine["cote_x"]).mean()
        prob_impl_2 = (1.0 / df_termine["cote_2"]).mean()

        return BiasStats(
            taux_1=float(taux_1),
            taux_N=float(taux_N),
            taux_2=float(taux_2),
            edge_1=float(taux_1 - prob_impl_1),
            edge_N=float(taux_N - prob_impl_N),
            edge_2=float(taux_2 - prob_impl_2),
            n_matches=total,
        )

    def _construire_classement_cache(self) -> Dict:
        """Construit le cache classement depuis le DataFrame pandas."""
        cache = {}
        df = self._classement_df.sort_values("journee")

        for _, row in df.iterrows():
            team_id = int(row["equipe_id"])
            journee = int(row["journee"])
            cache[(team_id, journee)] = {
                "position": int(row["position"]) if pd.notna(row["position"]) else 10,
                "points": int(row["points"]) if pd.notna(row["points"]) else 0,
                "forme": str(row["forme"]) if pd.notna(row.get("forme", "")) else "",
            }
        return cache

    def _charger_matches(self) -> List[Dict]:
        """Filtre les matchs TERMINE dans la plage de journées."""
        df = self._matches_df
        mask = (
            (df["journee"] >= self.journee_debut)
            & (df["journee"] <= self.journee_fin)
            & (df["status"] == "TERMINE")
            & df["cote_1"].notna()
            & df["cote_x"].notna()
            & df["cote_2"].notna()
        )
        if self.feature_session_id is not None:
            mask &= df["session_id"] == self.feature_session_id

        df_filtered = df[mask].sort_values(["journee", "id"])
        return df_filtered.to_dict("records")

    def _get_observation(self) -> np.ndarray:
        """Construit l'observation 14-features depuis les données en cache."""
        if self.match_actuel is None:
            return np.zeros(14, dtype=np.float32)

        m = self.match_actuel
        journee = m["journee"]
        dom_id = m["equipe_dom_id"]
        ext_id = m["equipe_ext_id"]

        # Récupérer classement depuis cache (même logique que BettingEnv)
        from bisect import bisect_left

        def get_team_data(team_id: int) -> Dict:
            # Trouver la dernière journée de classement strictement < journee
            team_keys = sorted(
                [k[1] for k in self._classement_cache if k[0] == team_id and k[1] < journee]
            )
            if team_keys:
                last_j = team_keys[-1]
                return self._classement_cache.get((team_id, last_j), {})
            return {"position": 10, "points": 0, "forme": ""}

        dom_data = get_team_data(dom_id)
        ext_data = get_team_data(ext_id)

        # Calcul des features (mêmes formules que observation.py)
        from ..environment.observation import calculer_momentum, calculer_serie

        rank_diff = (dom_data.get("position", 10) - ext_data.get("position", 10) + 19) / 38
        pts_diff = (dom_data.get("points", 0) - ext_data.get("points", 0) + 60) / 120
        mom_dom = calculer_momentum(dom_data.get("forme", ""))
        mom_ext = calculer_momentum(ext_data.get("forme", ""))
        streak_dom = (calculer_serie(dom_data.get("forme", "")) + 1.0) / 2.0
        streak_ext = (calculer_serie(ext_data.get("forme", "")) + 1.0) / 2.0

        cote_1 = float(m["cote_1"])
        cote_x = float(m["cote_x"])
        cote_2 = float(m["cote_2"])

        p1 = 1.0 / cote_1 if cote_1 > 0 else 0.33
        px = 1.0 / cote_x if cote_x > 0 else 0.33
        p2 = 1.0 / cote_2 if cote_2 > 0 else 0.33
        total = p1 + px + p2
        if total > 0:
            p1, px, p2 = p1 / total, px / total, p2 / total

        ev_1_raw = self.bias_stats.get_ev("1", cote_1)
        ev_2_raw = self.bias_stats.get_ev("2", cote_2)
        ev_1 = max(0.0, min(1.0, (ev_1_raw + 0.20) / 0.40))
        ev_2 = max(0.0, min(1.0, (ev_2_raw + 0.20) / 0.40))

        obs = np.array([
            np.clip(rank_diff, 0, 1),
            np.clip(pts_diff, 0, 1),
            mom_dom, mom_ext,
            p1, px, p2,
            streak_dom, streak_ext,
            self.bias_stats.taux_1,
            self.bias_stats.taux_N,
            self.bias_stats.taux_2,
            ev_1, ev_2,
        ], dtype=np.float32)

        return np.clip(obs, 0.0, 1.0)

    def _get_info(self) -> Dict:
        return {
            "capital": self.capital,
            "score_zeus": self.score_zeus,
            "journee": self.match_actuel["journee"] if self.match_actuel else 0,
            "matches_restants": len(self.matches_restants),
            "total_paris": self.total_paris,
            "paris_gagnants": self.paris_gagnants,
            "win_rate": self.paris_gagnants / max(self.total_paris, 1),
        }

    def reset(self, seed=None, options=None) -> Tuple[np.ndarray, Dict]:
        super().reset(seed=seed)
        self.capital = self.capital_initial
        self.risk_manager = RiskManager(self.capital_initial)
        self.score_zeus = 0
        self.historique_capital = self.risk_manager.historique_capital
        self.total_paris = 0
        self.paris_gagnants = 0

        self.matches_restants = self._charger_matches()
        if not self.matches_restants:
            raise ValueError(
                f"Aucun match TERMINE entre J{self.journee_debut} et J{self.journee_fin}"
            )
        self.match_actuel = self.matches_restants.pop(0)
        return self._get_observation(), self._get_info()

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        if self.match_actuel is None:
            raise RuntimeError("Appelez reset() d'abord.")

        type_pari = ACTION_SPACE_CONFIG[action]
        m = self.match_actuel

        cote_1 = float(m["cote_1"]) if m["cote_1"] else None
        cote_x = float(m["cote_x"]) if m["cote_x"] else None
        cote_2 = float(m["cote_2"]) if m["cote_2"] else None

        if type_pari == "1":
            cote_jouee = cote_1
        elif type_pari == "N":
            cote_jouee = cote_x
        elif type_pari == "2":
            cote_jouee = cote_2
        else:
            cote_jouee = None

        best_ev_dispo = self.bias_stats.best_ev(
            cote_1 or 10.0, cote_x or 10.0, cote_2 or 10.0
        )

        if type_pari == "Aucun" or cote_jouee is None:
            reward = calculer_recompense_skip(best_ev_dispo)
            profit_net, pari_gagne, mise_finale, ev = 0, None, 0, 0.0
        else:
            ev = self.bias_stats.get_ev(type_pari, cote_jouee)
            mise_kelly = self.risk_manager.calculer_mise_kelly(ev, cote_jouee, self.capital)

            if mise_kelly == 0:
                reward = calculer_recompense_skip(best_ev_dispo)
                profit_net, pari_gagne, mise_finale = 0, None, 0
            else:
                _, mise_finale, _ = self.risk_manager.valider_mise(mise_kelly)
                mise_finale = max(mise_finale, 0)

                pari_gagne = determiner_resultat(type_pari, int(m["score_dom"]), int(m["score_ext"]))
                self.total_paris += 1
                if pari_gagne:
                    self.paris_gagnants += 1

                if pari_gagne:
                    profit_net = int(mise_finale * (cote_jouee - 1))
                else:
                    profit_net = -mise_finale
                self.capital += profit_net
                self.risk_manager.mettre_a_jour_capital(self.capital)

                reward, self.score_zeus = calculer_recompense(
                    mise_finale, cote_jouee, pari_gagne, self.capital, self.score_zeus, ev=ev
                )

        terminated = self.capital < 1000
        episode_finished = terminated or not self.matches_restants
        if episode_finished:
            terminated = True
            self.match_actuel = None
        else:
            self.match_actuel = self.matches_restants.pop(0)

        return self._get_observation(), reward, terminated, False, self._get_info()

    def close(self):
        pass  # Pas de connexion DB à fermer
