"""
ZEUS v2 — Environnement de pari (Piliers 2, 3, 4, 5 intégrés).

Changements clés vs v1 :
- Espace d'action : 13 → 4 (Skip / Pari1 / PariN / Pari2)
- Mises : fixes arbitraires → Kelly dynamique selon l'EV
- Observation : 8 → 14 features (inclut séries, taux historiques, EV)
- Reward : basée sur l'EV, récompense les bonnes décisions probabilistes
- BiasStats : préchargées une seule fois par reset(), pas de SQL par step()
"""
from typing import Any, Dict, List, Optional, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ...core import config
from ...core.database import get_db_connection
from ..utils.rng_bias import BiasStats, DEFAULT_BIAS, calculer_biais_rng
from ..utils.risk_manager import RiskManager
from .observation import ObservationContext, construire_observation
from .reward import (
    calculer_recompense,
    calculer_recompense_skip,
    determiner_resultat,
)

# ─────────────────────────────────────────────────
# Espace d'action v2 : 4 actions discrètes
# La MISE n'est plus dans l'action — elle est calculée par Kelly dans step()
# ─────────────────────────────────────────────────
ACTION_SPACE_CONFIG = {
    0: "Aucun",   # Skip — ne pas parier sur ce match
    1: "1",       # Pari victoire domicile (mise Kelly)
    2: "N",       # Pari match nul (mise Kelly)
    3: "2",       # Pari victoire extérieur (mise Kelly)
}

# Limites de mise (Ar) — plancher et plafond de sécurité
_MISE_MIN = 1000
_MISE_MAX = 3000


class BettingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        capital_initial: int = config.DEFAULT_BANKROLL,
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

        # Espace d'observation v2 : 14 features
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(14,), dtype=np.float32
        )
        # Espace d'action v2 : 4 actions discrètes
        self.action_space = spaces.Discrete(len(ACTION_SPACE_CONFIG))

        self.capital = capital_initial
        self.score_zeus = 0
        self.journee_actuelle = journee_debut
        self.matches_restants: List[Dict] = []
        self.match_actuel: Optional[Dict] = None
        self.session_id: Optional[int] = None
        self.conn = None
        self.risk_manager = RiskManager(capital_initial)
        self.historique_capital: List[int] = []
        self.total_paris = 0
        self.paris_gagnants = 0
        self.feature_session_id = feature_session_id

        # Cache classement (préchargé par reset)
        self.classement_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._classement_cache_feature_session_id: Optional[int] = None

        # BiasStats préchargées (Pilier 1) — zéro SQL par step()
        self.bias_stats: BiasStats = DEFAULT_BIAS

    # ─────────────────────────────────────────────
    # PRÉCHARGEMENT DU CACHE CLASSEMENT
    # ─────────────────────────────────────────────
    def _precharger_classement_cache(self) -> None:
        if self.feature_session_id is None:
            self.classement_cache = {}
            self._classement_cache_feature_session_id = None
            return
        if (
            self._classement_cache_feature_session_id == self.feature_session_id
            and self.classement_cache
        ):
            return

        equipe_ids = set()
        match_journees = set()
        for m in self.matches_restants:
            equipe_ids.add(m["equipe_dom_id"])
            equipe_ids.add(m["equipe_ext_id"])
            match_journees.add(m["journee"])

        if not equipe_ids or not match_journees:
            self.classement_cache = {}
            self._classement_cache_feature_session_id = self.feature_session_id
            return

        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT equipe_id, journee, position, points, forme
            FROM classement
            WHERE session_id = %s
            """,
            (self.feature_session_id,),
        )
        rows = cursor.fetchall()

        rows_by_team: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            rows_by_team.setdefault(row["equipe_id"], []).append(row)
        for team_rows in rows_by_team.values():
            team_rows.sort(key=lambda r: r["journee"])

        from bisect import bisect_left

        required_journees = sorted(match_journees)
        self.classement_cache = {}
        for team_id in equipe_ids:
            team_rows = rows_by_team.get(team_id, [])
            team_days = [r["journee"] for r in team_rows]
            for j in required_journees:
                idx = bisect_left(team_days, j) - 1
                if idx >= 0:
                    rec = team_rows[idx]
                    position = rec["position"] if rec["position"] is not None else 10
                    points = rec["points"] if rec["points"] is not None else 0
                    forme = rec["forme"] or ""
                else:
                    position, points, forme = 10, 0, ""
                self.classement_cache[(team_id, j)] = {
                    "position": position,
                    "points": points,
                    "forme": forme,
                }

        self._classement_cache_feature_session_id = self.feature_session_id

    # ─────────────────────────────────────────────
    # RESET
    # ─────────────────────────────────────────────
    def reset(
        self, seed: Optional[int] = None, options: Optional[Dict] = None
    ) -> Tuple[np.ndarray, Dict]:
        super().reset(seed=seed)
        self.capital = self.capital_initial
        self.risk_manager = RiskManager(self.capital_initial)
        self.score_zeus = 0
        self.journee_actuelle = self.journee_debut
        self.historique_capital = self.risk_manager.historique_capital
        self.total_paris = 0
        self.paris_gagnants = 0

        if self.conn is None:
            self.conn_context = get_db_connection(write=(self.mode == "train"))
            self.conn = self.conn_context.__enter__()

        if self.mode == "train":
            from ..database.queries import create_session
            self.session_id = create_session(
                self.capital_initial, "TRAINING", self.version_ia, self.conn
            )
        else:
            self.session_id = None

        self._charger_matches()
        self._precharger_classement_cache()

        # ── Pilier 1 : Précharger les biais RNG (1 seule requête) ──
        self.bias_stats = calculer_biais_rng(
            self.conn,
            session_id=None,   # Utiliser TOUT l'historique pour la fiabilité max
        )

        if len(self.matches_restants) > 0:
            self.match_actuel = self.matches_restants.pop(0)
        else:
            raise ValueError("Aucun match disponible pour cet épisode")

        return self._get_observation(), self._get_info()

    # ─────────────────────────────────────────────
    # CHARGEMENT DES MATCHS
    # ─────────────────────────────────────────────
    def _charger_matches(self):
        from ..database.queries import get_matches_for_journee

        all_matches = []
        for journee in range(self.journee_debut, self.journee_fin + 1):
            matches = get_matches_for_journee(
                journee, self.conn, session_id=self.feature_session_id
            )
            matches_valides = [
                m
                for m in matches
                if m["status"] == "TERMINE"
                and m["cote_1"] is not None
                and m["cote_x"] is not None
                and m["cote_2"] is not None
            ]
            all_matches.extend(matches_valides)
        self.matches_restants = all_matches
        if len(all_matches) == 0:
            raise ValueError(
                f"Aucun match TERMINE trouvé entre J{self.journee_debut} et J{self.journee_fin}"
            )

    # ─────────────────────────────────────────────
    # OBSERVATION (14 features v2)
    # ─────────────────────────────────────────────
    def _get_observation(self) -> np.ndarray:
        if self.match_actuel is None:
            return np.zeros(14, dtype=np.float32)
        context = ObservationContext(
            equipe_dom_id=self.match_actuel["equipe_dom_id"],
            equipe_ext_id=self.match_actuel["equipe_ext_id"],
            journee=self.match_actuel["journee"],
            cote_1=self.match_actuel["cote_1"],
            cote_x=self.match_actuel["cote_x"],
            cote_2=self.match_actuel["cote_2"],
            session_id=self.feature_session_id,
        )
        return construire_observation(
            context,
            self.conn,
            classement_cache=self.classement_cache,
            bias_stats=self.bias_stats,  # Pilier 1 & 3 — transmis à l'observation
        )

    def _get_info(self) -> Dict:
        return {
            "capital": self.capital,
            "score_zeus": self.score_zeus,
            "journee": self.match_actuel["journee"] if self.match_actuel else 0,
            "matches_restants": len(self.matches_restants),
            "total_paris": self.total_paris,
            "paris_gagnants": self.paris_gagnants,
            "win_rate": self.paris_gagnants / max(self.total_paris, 1),
            "bias_n_matches": self.bias_stats.n_matches,
        }

    # ─────────────────────────────────────────────
    # STEP — Cœur de la décision ZEUS v2
    # ─────────────────────────────────────────────
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        if self.match_actuel is None:
            raise RuntimeError("Pas de match actuel. Appelez reset() d'abord.")
        if action not in ACTION_SPACE_CONFIG:
            raise ValueError(f"Action invalide pour ZEUS : {action}")

        type_pari = ACTION_SPACE_CONFIG[action]

        # ── Récupérer les cotes du match ──
        cote_1 = float(self.match_actuel["cote_1"]) if self.match_actuel["cote_1"] else None
        cote_x = float(self.match_actuel["cote_x"]) if self.match_actuel["cote_x"] else None
        cote_2 = float(self.match_actuel["cote_2"]) if self.match_actuel["cote_2"] else None

        # ── Identifier la cote jouée ──
        if type_pari == "1":
            cote_jouee = cote_1
        elif type_pari == "N":
            cote_jouee = cote_x
        elif type_pari == "2":
            cote_jouee = cote_2
        else:
            cote_jouee = None

        # ── Meilleur EV disponible (pour récompense Skip) ──
        best_ev_dispo = self.bias_stats.best_ev(
            cote_1 or 10.0, cote_x or 10.0, cote_2 or 10.0
        )

        # ── Action Skip ──
        if type_pari == "Aucun" or cote_jouee is None:
            reward = calculer_recompense_skip(best_ev_dispo)
            profit_net = 0
            pari_gagne = None
            mise_finale = 0
            ev = 0.0
        else:
            # ── Pilier 3 : Calculer l'EV du pari choisi ──
            ev = self.bias_stats.get_ev(type_pari, cote_jouee)

            # ── Pilier 4 : Mise Kelly dynamique ──
            mise_kelly = self.risk_manager.calculer_mise_kelly(ev, cote_jouee, self.capital)

            # Si EV négatif → Kelly retourne 0 → on simule un Skip
            if mise_kelly == 0:
                reward = calculer_recompense_skip(best_ev_dispo)
                profit_net = 0
                pari_gagne = None
                mise_finale = 0
            else:
                # Valider la mise contre la bankroll disponible
                est_valide, mise_finale, _ = self.risk_manager.valider_mise(mise_kelly)
                if not est_valide:
                    mise_finale = max(mise_kelly, 0)

                # ── Résolution du pari ──
                pari_gagne = determiner_resultat(
                    type_pari,
                    self.match_actuel["score_dom"],
                    self.match_actuel["score_ext"],
                )
                self.total_paris += 1
                if pari_gagne:
                    self.paris_gagnants += 1

                if pari_gagne is True:
                    profit_net = int(mise_finale * (cote_jouee - 1))
                    self.capital += profit_net
                elif pari_gagne is False:
                    profit_net = -mise_finale
                    self.capital += profit_net
                else:
                    profit_net = 0

                self.risk_manager.mettre_a_jour_capital(self.capital)

                # ── Pilier 5 : Récompense EV+ ──
                reward, self.score_zeus = calculer_recompense(
                    mise_finale, cote_jouee, pari_gagne,
                    self.capital, self.score_zeus, ev=ev,
                )

        # ── Enregistrement en base (mode train uniquement) ──
        if self.session_id is not None and mise_finale > 0:
            from ..database.queries import PariRecord, enregistrer_pari
            enregistrer_pari(
                PariRecord(
                    session_id=self.session_id,
                    prediction_id=self.match_actuel["id"],
                    journee=self.match_actuel["journee"],
                    type_pari=type_pari,
                    mise_ar=int(mise_finale),
                    pourcentage_bankroll=float(mise_finale / self.capital) if self.capital > 0 else 0,
                    cote_jouee=float(cote_jouee) if cote_jouee else None,
                    resultat=1 if pari_gagne is True else (0 if pari_gagne is False else None),
                    profit_net=int(profit_net),
                    bankroll_apres=int(self.capital),
                    probabilite_implicite=float(1 / cote_jouee) if cote_jouee else None,
                    action_id=int(action),
                ),
                conn=self.conn,
            )

        # ── Fin d'épisode ──
        terminated = self.capital < 1000
        episode_finished = terminated or len(self.matches_restants) == 0
        if episode_finished:
            terminated = True
            if self.session_id is not None:
                from ..database.queries import finaliser_session
                profit_total = self.capital - self.capital_initial
                finaliser_session(
                    self.session_id, self.capital, profit_total,
                    self.score_zeus, self.conn,
                )
                self.conn.commit()
            self.match_actuel = None
        else:
            self.match_actuel = self.matches_restants.pop(0)

        return self._get_observation(), reward, terminated, False, self._get_info()

    def close(self):
        if self.conn is not None:
            self.conn_context.__exit__(None, None, None)
            self.conn = None
