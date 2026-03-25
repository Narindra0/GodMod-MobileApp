import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from src.core import config
from src.core.database import get_db_connection
from src.zeus.environment.betting_env import BettingEnv
from src.zeus.models.ppo_agent import load_ppo_agent
from src.zeus.utils.metrics import PerformanceInput, afficher_rapport, generer_rapport_performance


@dataclass(frozen=True)
class EvaluationConfig:
    model_path: str
    journee_debut: int = 1
    journee_fin: int = 37
    n_episodes: int = 1
    deterministic: bool = True
    feature_session_id: Optional[int] = None


def _select_completed_training_session(conn: Any) -> Optional[int]:
    """
    Sélectionne une session dont les matches couvrent au moins les journées 1 à 37 (incluses).
    Utilisé pour fournir à ZEUS les features de classement cohérentes.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id
        FROM sessions s
        JOIN matches m ON m.session_id = s.id
        WHERE m.status = 'TERMINE'
        GROUP BY s.id
        HAVING COUNT(DISTINCT CASE WHEN m.journee BETWEEN 1 AND 37 THEN m.journee END) = 37
        ORDER BY s.id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    return row["id"] if row else None


def evaluate_model(cfg: EvaluationConfig):
    print("\n" + "=" * 60)
    print("EVALUATION ZEUS")
    print("=" * 60)
    print(f"Modele:    {cfg.model_path}")
    print(f"Journees:  {cfg.journee_debut} a {cfg.journee_fin}")
    print(f"Episodes:  {cfg.n_episodes}")
    print("-" * 60)

    feature_session_id = cfg.feature_session_id
    if feature_session_id is None:
        with get_db_connection() as conn:
            feature_session_id = _select_completed_training_session(conn)
        if feature_session_id is None:
            raise ValueError(
                "Aucune session complète trouvée pour les features ZEUS (journées 1 à 37)."
            )

    env = BettingEnv(
        capital_initial=config.DEFAULT_BANKROLL,
        journee_debut=cfg.journee_debut,
        journee_fin=cfg.journee_fin,
        mode="eval",
        version_ia="evaluation",
        feature_session_id=feature_session_id,
    )
    print("Chargement du modele...")
    model = load_ppo_agent(cfg.model_path, env=env)
    all_rapports = []
    for episode in range(cfg.n_episodes):
        print(f"\nEpisode {episode + 1}/{cfg.n_episodes}")
        obs, info = env.reset()
        done = False
        total_reward = 0
        while not done:
            action, _states = model.predict(obs, deterministic=cfg.deterministic)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            done = terminated or truncated
        rapport = generer_rapport_performance(
            PerformanceInput(
                capital_initial=config.DEFAULT_BANKROLL,
                capital_final=env.capital,
                capital_history=env.historique_capital,
                total_matches=len(env.historique_capital) - 1,
                total_paris=env.total_paris,
                paris_gagnants=env.paris_gagnants,
            )
        )
        rapport["total_reward"] = total_reward
        all_rapports.append(rapport)
        afficher_rapport(rapport)
    if cfg.n_episodes > 1:
        print("\n" + "=" * 60)
        print("MOYENNES SUR TOUS LES EPISODES")
        print("=" * 60)
        avg_roi = sum(r["roi_percent"] for r in all_rapports) / cfg.n_episodes
        avg_win_rate = sum(r["win_rate_percent"] for r in all_rapports) / cfg.n_episodes
        avg_sharpe = sum(r["sharpe_ratio"] for r in all_rapports) / cfg.n_episodes
        avg_drawdown = sum(r["max_drawdown_percent"] for r in all_rapports) / cfg.n_episodes
        print(f"ROI moyen:        {avg_roi:+.2f}%")
        print(f"Win rate moyen:   {avg_win_rate:.2f}%")
        print(f"Sharpe moyen:     {avg_sharpe:.3f}")
        print(f"Max DD moyen:     {avg_drawdown:.2f}%")
        print("=" * 60)
    env.close()
    print("\nEvaluation terminee!")


def main():
    parser = argparse.ArgumentParser(description="Évaluer un modèle ZEUS entraîné")
    parser.add_argument("--model", type=str, required=True, help="Chemin vers le modèle .zip (sans extension)")
    parser.add_argument("--journee-debut", type=int, help="Première journée (auto-détecté si omis)")
    parser.add_argument("--journee-fin", type=int, help="Dernière journée (auto-détecté si omis)")
    parser.add_argument("--episodes", type=int, default=1, help="Nombre d'épisodes à évaluer")
    parser.add_argument(
        "--feature-session-id",
        type=int,
        default=None,
        help="ID de session DB à utiliser pour les features de classement ZEUS (auto si omis)",
    )
    parser.add_argument(
        "--stochastic", action="store_true", help="Utiliser des actions stochastiques au lieu de déterministes"
    )
    args = parser.parse_args()
    if args.journee_debut is None or args.journee_fin is None:
        from src.zeus.database.queries import get_available_seasons

        with get_db_connection() as conn:
            seasons = get_available_seasons(conn)
        if len(seasons) == 0:
            print("❌ Aucune saison trouvée dans la base de données!")
            sys.exit(1)
        args.journee_debut = seasons[-1]
        args.journee_fin = args.journee_debut + 36
        print(f"Auto-détection: Évaluation sur journées {args.journee_debut}-{args.journee_fin}")
    evaluate_model(
        EvaluationConfig(
            model_path=args.model,
            journee_debut=args.journee_debut,
            journee_fin=args.journee_fin,
            n_episodes=args.episodes,
            deterministic=not args.stochastic,
            feature_session_id=args.feature_session_id,
        )
    )


if __name__ == "__main__":
    main()
