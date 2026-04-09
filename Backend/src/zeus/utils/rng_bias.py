"""
Pilier 1 — Détection des biais du RNG Bet261.

Calcule l'écart entre les taux réels observés sur l'historique complet
et les probabilités implicites annoncées par les cotes.
Cet écart (edge) est la base du Value Betting (Pilier 3).

Usage:
    bias = calculer_biais_rng(conn)
    ev = bias.get_ev("1", cote_1)           # Expected Value
    kelly = bias.get_kelly_fraction("1", cote_1)  # Fraction à miser
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Valeurs par défaut si les données sont insuffisantes (<50 matchs)
_TAUX_1_DEFAULT = 0.45
_TAUX_N_DEFAULT = 0.26
_TAUX_2_DEFAULT = 0.29
_KELLY_MAX = 0.10   # Plafond de sécurité : jamais plus de 10% de la bankroll
_KELLY_MIN_EV = 0.01  # EV minimum pour considérer un pari


@dataclass
class BiasStats:
    """Statistiques de biais du RNG Bet261 calculées sur l'historique."""
    taux_1: float    # Taux réel de victoire domicile observé
    taux_N: float    # Taux réel de nul observé
    taux_2: float    # Taux réel de victoire extérieur observé
    edge_1: float    # Biais RNG issue 1 = taux_1 - prob_implicite_moyenne_1
    edge_N: float    # Biais RNG issue N = taux_N - prob_implicite_moyenne_N
    edge_2: float    # Biais RNG issue 2 = taux_2 - prob_implicite_moyenne_2
    n_matches: int   # Nombre de matchs analysés (fiabilité)

    def get_ev(self, type_pari: str, cote: float) -> float:
        """
        Calcule l'Expected Value pour un pari.
        EV = (taux_observé × cote) - 1
        EV > 0  → pari à valeur positive (à jouer sur le long terme)
        EV ≤ 0  → pari sans valeur (bookmaker a l'avantage)
        """
        if not cote or cote <= 1.0:
            return -1.0
        cote = float(cote)
        if type_pari == "1":
            return (self.taux_1 * cote) - 1.0
        elif type_pari == "N":
            return (self.taux_N * cote) - 1.0
        elif type_pari == "2":
            return (self.taux_2 * cote) - 1.0
        return -1.0

    def get_kelly_fraction(self, type_pari: str, cote: float) -> float:
        """
        Critère de Kelly : f* = edge / (cote - 1)
        Plafonnée à KELLY_MAX (10%) pour éviter la surexposition.
        Retourne 0 si EV négatif = on ne parie pas.
        """
        ev = self.get_ev(type_pari, cote)
        if ev < _KELLY_MIN_EV or float(cote) <= 1.0:
            return 0.0
        fraction = ev / (float(cote) - 1.0)
        return min(fraction, _KELLY_MAX)

    def best_ev(self, cote_1: float, cote_x: float, cote_2: float) -> float:
        """Retourne le meilleur EV disponible sur un match."""
        return max(
            self.get_ev("1", cote_1),
            self.get_ev("N", cote_x),
            self.get_ev("2", cote_2),
        )

    def __repr__(self) -> str:
        return (
            f"BiasStats(n={self.n_matches} | "
            f"taux: 1={self.taux_1:.3f} N={self.taux_N:.3f} 2={self.taux_2:.3f} | "
            f"edge: 1={self.edge_1:+.3f} N={self.edge_N:+.3f} 2={self.edge_2:+.3f})"
        )


# Instance par défaut utilisée si pas assez de données
DEFAULT_BIAS = BiasStats(
    taux_1=_TAUX_1_DEFAULT,
    taux_N=_TAUX_N_DEFAULT,
    taux_2=_TAUX_2_DEFAULT,
    edge_1=0.0,
    edge_N=0.0,
    edge_2=0.0,
    n_matches=0,
)


def calculer_biais_rng(
    conn: Any,
    session_id: Optional[int] = None,
    min_matches: int = 50,
) -> BiasStats:
    """
    Calcule les biais du RNG à partir de l'historique complet des matchs TERMINE.
    Utilise une seule requête SQL agrégée — résultat à mettre en cache.

    Args:
        conn: Connexion PostgreSQL active
        session_id: Si fourni, limite l'analyse à cette session.
                    Si None, utilise tout l'historique (recommandé).
        min_matches: Nombre minimum de matchs pour une statistique fiable.

    Returns:
        BiasStats avec les taux réels et les edges exploitables.
        Retourne DEFAULT_BIAS si données insuffisantes.
    """
    cursor = conn.cursor()

    session_filter = "AND m.session_id = %s" if session_id else ""
    params = (session_id,) if session_id else ()

    # Une seule requête agrégée : taux réels + moyennes probabilités implicites
    query = f"""
        SELECT
            COUNT(*) AS total,
            COUNT(CASE WHEN m.score_dom > m.score_ext THEN 1 END) AS wins_1,
            COUNT(CASE WHEN m.score_dom = m.score_ext THEN 1 END) AS wins_n,
            COUNT(CASE WHEN m.score_dom < m.score_ext THEN 1 END) AS wins_2,
            AVG(CASE WHEN m.cote_1 > 1 THEN 1.0 / m.cote_1 END)  AS prob_impl_1,
            AVG(CASE WHEN m.cote_x > 1 THEN 1.0 / m.cote_x END)  AS prob_impl_n,
            AVG(CASE WHEN m.cote_2 > 1 THEN 1.0 / m.cote_2 END)  AS prob_impl_2
        FROM matches m
        WHERE m.status = 'TERMINE'
          AND m.cote_1 IS NOT NULL
          AND m.cote_x IS NOT NULL
          AND m.cote_2 IS NOT NULL
          AND m.score_dom IS NOT NULL
          AND m.score_ext IS NOT NULL
          {session_filter}
    """
    try:
        cursor.execute(query, params)
        row = cursor.fetchone()
    except Exception as e:
        logger.error(f"Erreur calcul biais RNG : {e}")
        return DEFAULT_BIAS

    if not row or not row["total"] or row["total"] < min_matches:
        n = row["total"] if row else 0
        logger.warning(
            f"Données insuffisantes pour le biais RNG ({n} matchs, minimum {min_matches}). "
            "Utilisation des valeurs par défaut."
        )
        return DEFAULT_BIAS

    total = row["total"]
    taux_1 = row["wins_1"] / total
    taux_n = row["wins_n"] / total
    taux_2 = row["wins_2"] / total

    # Probabilités implicites moyennes (sans marge bookmaker)
    prob_impl_1 = float(row["prob_impl_1"] or _TAUX_1_DEFAULT)
    prob_impl_n = float(row["prob_impl_n"] or _TAUX_N_DEFAULT)
    prob_impl_2 = float(row["prob_impl_2"] or _TAUX_2_DEFAULT)

    stats = BiasStats(
        taux_1=taux_1,
        taux_N=taux_n,
        taux_2=taux_2,
        edge_1=taux_1 - prob_impl_1,
        edge_N=taux_n - prob_impl_n,
        edge_2=taux_2 - prob_impl_2,
        n_matches=total,
    )

    logger.info(f"Biais RNG calculé : {stats}")
    return stats
