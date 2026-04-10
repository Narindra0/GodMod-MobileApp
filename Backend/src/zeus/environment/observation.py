"""
Piliers 2 & 3 — Observation enrichie (8 → 14 features) + Expected Value.

Nouvelles features ajoutées :
  [7]  streak_dom    — Série victoires/défaites domicile (normalisée)
  [8]  streak_ext    — Série victoires/défaites extérieur
  [9]  taux_1_hist   — Taux historique de victoire domicile (vs cotes Bet261)
  [10] taux_x_hist   — Taux historique de nul
  [11] taux_2_hist   — Taux historique de victoire extérieur
  [12] ev_1          — Expected Value pari 1 (normalisé)
  [13] ev_2          — Expected Value pari 2 (normalisé)
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
from src.core.system.session_manager import get_active_session

from ..utils.rng_bias import DEFAULT_BIAS, BiasStats

logger = logging.getLogger(__name__)

# Constante pour normaliser l'EV dans [0, 1]
# EV typique sur du football virtuel : entre -0.2 et +0.2
_EV_NORM_MIN = -0.20
_EV_NORM_MAX = 0.20


@dataclass(frozen=True)
class ObservationContext:
    equipe_dom_id: int
    equipe_ext_id: int
    journee: int
    cote_1: float
    cote_x: float
    cote_2: float
    session_id: Optional[int] = None


def calculer_momentum(forme: Optional[str]) -> float:
    """Momentum sur les 5 derniers matchs. [0, 1]"""
    if not forme or len(forme) == 0:
        return 0.5
    score = 0.0
    for result in forme[-5:]:
        if result == "V":
            score += 1.0
        elif result == "N":
            score += 0.5
    return score / min(len(forme), 5)


def calculer_serie(forme: Optional[str]) -> float:
    """
    Série courante : résultats consécutifs identiques à la fin de forme.
    Victoires → valeur positive, Défaites → valeur négative.
    Normalisé dans [-1, 1] (base 5 matchs max).
    """
    if not forme or len(forme) == 0:
        return 0.0
    last = forme[-1]
    count = 0
    for c in reversed(forme):
        if c == last:
            count += 1
        else:
            break
    count = min(count, 5)
    if last == "V":
        return count / 5.0
    elif last == "D":
        return -count / 5.0
    return 0.0  # Nul = neutre


def _normaliser_ev(ev: float) -> float:
    """Normalise l'EV dans [0, 1] pour l'observation."""
    clamped = max(_EV_NORM_MIN, min(_EV_NORM_MAX, ev))
    return (clamped - _EV_NORM_MIN) / (_EV_NORM_MAX - _EV_NORM_MIN)


def extraire_features_classement(
    equipe_dom_id: int,
    equipe_ext_id: int,
    journee: int,
    conn: Any,
    session_id: Optional[int] = None,
    classement_cache: Optional[Dict[tuple, Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """
    Extrait les features de classement pour les deux équipes.
    Retourne aussi les séries en cours (streak) issues du champ 'forme'.
    """
    if classement_cache is not None:
        dom_data = classement_cache.get(
            (equipe_dom_id, journee), {"position": 10, "points": 0, "forme": ""}
        )
        ext_data = classement_cache.get(
            (equipe_ext_id, journee), {"position": 10, "points": 0, "forme": ""}
        )
        dom_data = {
            "position": dom_data.get("position") if dom_data.get("position") is not None else 10,
            "points": dom_data.get("points") if dom_data.get("points") is not None else 0,
            "forme": dom_data.get("forme") or "",
        }
        ext_data = {
            "position": ext_data.get("position") if ext_data.get("position") is not None else 10,
            "points": ext_data.get("points") if ext_data.get("points") is not None else 0,
            "forme": ext_data.get("forme") or "",
        }
    else:
        cursor = conn.cursor()
        if session_id is None:
            active_session = get_active_session()
            session_id = active_session["id"]
        cursor.execute(
            """
            SELECT equipe_id, position, points, forme
            FROM classement
            WHERE session_id = %s AND journee = (
                SELECT MAX(journee)
                FROM classement
                WHERE session_id = %s AND journee < %s
            )
            AND equipe_id IN (%s, %s)
            """,
            (session_id, session_id, journee, equipe_dom_id, equipe_ext_id),
        )
        rows = cursor.fetchall()
        data = {}
        for row in rows:
            eid = row["equipe_id"]
            data[eid] = {
                "position": row["position"] if row["position"] is not None else 10,
                "points": row["points"] if row["points"] is not None else 0,
                "forme": row["forme"] or "",
            }
        dom_data = data.get(equipe_dom_id, {"position": 10, "points": 0, "forme": ""})
        ext_data = data.get(equipe_ext_id, {"position": 10, "points": 0, "forme": ""})

    return {
        "rank_diff": dom_data["position"] - ext_data["position"],
        "points_diff": dom_data["points"] - ext_data["points"],
        "momentum_dom": calculer_momentum(dom_data["forme"]),
        "momentum_ext": calculer_momentum(ext_data["forme"]),
        "streak_dom": calculer_serie(dom_data["forme"]),   # Pilier 2 - nouveau
        "streak_ext": calculer_serie(ext_data["forme"]),   # Pilier 2 - nouveau
    }


def extraire_features_cotes(cote_1: float, cote_x: float, cote_2: float) -> Dict[str, float]:
    """Probabilités implicites normalisées (somme ≈ 1 après normalisation)."""
    cote_1 = float(cote_1) if cote_1 is not None else None
    cote_x = float(cote_x) if cote_x is not None else None
    cote_2 = float(cote_2) if cote_2 is not None else None

    prob_1 = 1.0 / cote_1 if cote_1 and cote_1 > 0 else 0.33
    prob_x = 1.0 / cote_x if cote_x and cote_x > 0 else 0.33
    prob_2 = 1.0 / cote_2 if cote_2 and cote_2 > 0 else 0.33
    total = prob_1 + prob_x + prob_2
    if total > 0:
        prob_1 /= total
        prob_x /= total
        prob_2 /= total
    return {"prob_1": prob_1, "prob_x": prob_x, "prob_2": prob_2}


def construire_observation(
    context: ObservationContext,
    conn: Any,
    classement_cache: Optional[Dict[tuple, Dict[str, Any]]] = None,
    bias_stats: Optional[BiasStats] = None,
) -> np.ndarray:
    """
    Construit le vecteur d'observation ZEUS v2 — 14 features.

    Features [0-3]  : classement (inchangées)
    Features [4-6]  : probabilités implicites des cotes (inchangées)
    Features [7-8]  : séries en cours (NOUVEAU — Pilier 2)
    Features [9-11] : taux historiques RNG (NOUVEAU — Pilier 2)
    Features [12-13]: Expected Value (NOUVEAU — Pilier 3)
    """
    stats = bias_stats if bias_stats is not None else DEFAULT_BIAS

    class_features = extraire_features_classement(
        context.equipe_dom_id,
        context.equipe_ext_id,
        context.journee,
        conn,
        context.session_id,
        classement_cache=classement_cache,
    )
    cote_features = extraire_features_cotes(context.cote_1, context.cote_x, context.cote_2)

    # EV normalisés dans [0, 1] (Pilier 3)
    ev_1 = _normaliser_ev(stats.get_ev("1", context.cote_1))
    ev_2 = _normaliser_ev(stats.get_ev("2", context.cote_2))

    # Streak normalisé dans [0, 1] depuis [-1, 1]
    streak_dom_norm = (class_features["streak_dom"] + 1.0) / 2.0
    streak_ext_norm = (class_features["streak_ext"] + 1.0) / 2.0

    observation = np.array(
        [
            # --- Features existantes ---
            (class_features["rank_diff"] + 19) / 38,        # [0] rank_diff
            (class_features["points_diff"] + 60) / 120,     # [1] points_diff
            class_features["momentum_dom"],                  # [2] momentum_dom
            class_features["momentum_ext"],                  # [3] momentum_ext
            cote_features["prob_1"],                         # [4] prob_1 (implicite)
            cote_features["prob_x"],                         # [5] prob_x (implicite)
            cote_features["prob_2"],                         # [6] prob_2 (implicite)
            # --- Nouvelles features v2 ---
            streak_dom_norm,                                 # [7] streak_dom
            streak_ext_norm,                                 # [8] streak_ext
            stats.taux_1,                                    # [9] taux_1_hist (RNG)
            stats.taux_N,                                    # [10] taux_x_hist (RNG)
            stats.taux_2,                                    # [11] taux_2_hist (RNG)
            ev_1,                                            # [12] ev_1 normalisé
            ev_2,                                            # [13] ev_2 normalisé
        ],
        dtype=np.float32,
    )
    return np.clip(observation, 0.0, 1.0)
