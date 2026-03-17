import argparse
import sys
from pathlib import Path
import sqlite3
BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from src.zeus.environment.betting_env import BettingEnv
from src.zeus.models.ppo_agent import load_ppo_agent
from src.zeus.utils.metrics import generer_rapport_performance, afficher_rapport
from src.core import config
def evaluate_model(
    model_path: str,
    db_path: str = None,
    journee_debut: int = 1,
    journee_fin: int = 38,
    n_episodes: int = 1,
    deterministic: bool = True
):
    current_db_path = db_path or config.DB_NAME
    print("\n" + "=" * 60)
    print("🔍 ÉVALUATION ZEUS")
    print("=" * 60)
    print(f"Modèle:    {model_path}")
    print(f"Base:      {current_db_path}")
    print(f"Journées:  {journee_debut} à {journee_fin}")
    print(f"Episodes:  {n_episodes}")
    print("-" * 60)
    env = BettingEnv(
        db_path=current_db_path,
        capital_initial=20000,
        journee_debut=journee_debut,
        journee_fin=journee_fin,
        mode='eval',
        version_ia='evaluation'
    )
    print("📦 Chargement du modèle...")
    model = load_ppo_agent(model_path, env=env)
    all_rapports = []
    for episode in range(n_episodes):
        print(f"\n📊 Épisode {episode + 1}/{n_episodes}")
        obs, info = env.reset()
        done = False
        total_reward = 0
        while not done:
            action, _states = model.predict(obs, deterministic=deterministic)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += reward
            done = terminated or truncated
        rapport = generer_rapport_performance(
            capital_initial=20000,
            capital_final=env.capital,
            capital_history=env.historique_capital,
            total_matches=len(env.historique_capital) - 1,
            total_paris=env.total_paris,
            paris_gagnants=env.paris_gagnants
        )
        rapport['total_reward'] = total_reward
        all_rapports.append(rapport)
        afficher_rapport(rapport)
    if n_episodes > 1:
        print("\n" + "=" * 60)
        print("📊 MOYENNES SUR TOUS LES ÉPISODES")
        print("=" * 60)
        avg_roi = sum(r['roi_percent'] for r in all_rapports) / n_episodes
        avg_win_rate = sum(r['win_rate_percent'] for r in all_rapports) / n_episodes
        avg_sharpe = sum(r['sharpe_ratio'] for r in all_rapports) / n_episodes
        avg_drawdown = sum(r['max_drawdown_percent'] for r in all_rapports) / n_episodes
        print(f"ROI moyen:        {avg_roi:+.2f}%")
        print(f"Win rate moyen:   {avg_win_rate:.2f}%")
        print(f"Sharpe moyen:     {avg_sharpe:.3f}")
        print(f"Max DD moyen:     {avg_drawdown:.2f}%")
        print("=" * 60)
    env.close()
    print("\n✅ Évaluation terminée!")
def main():
    parser = argparse.ArgumentParser(
        description="Évaluer un modèle ZEUS entraîné"
    )
    parser.add_argument(
        '--model',
        type=str,
        required=True,
        help='Chemin vers le modèle .zip (sans extension)'
    )
    parser.add_argument(
        '--db',
        type=str,
        default=config.DB_NAME,
        help='Chemin vers la base de données'
    )
    parser.add_argument(
        '--journee-debut',
        type=int,
        help='Première journée (auto-détecté si omis)'
    )
    parser.add_argument(
        '--journee-fin',
        type=int,
        help='Dernière journée (auto-détecté si omis)'
    )
    parser.add_argument(
        '--episodes',
        type=int,
        default=1,
        help='Nombre d\'épisodes à évaluer'
    )
    parser.add_argument(
        '--stochastic',
        action='store_true',
        help='Utiliser des actions stochastiques au lieu de déterministes'
    )
    args = parser.parse_args()
    if args.journee_debut is None or args.journee_fin is None:
        from src.zeus.database.queries import get_available_seasons
        conn = sqlite3.connect(args.db)
        seasons = get_available_seasons(conn)
        conn.close()
        if len(seasons) == 0:
            print("❌ Aucune saison trouvée dans la base de données!")
            sys.exit(1)
        args.journee_debut = seasons[-1]
        args.journee_fin = args.journee_debut + 37
        print(f"Auto-détection: Évaluation sur journées {args.journee_debut}-{args.journee_fin}")
    evaluate_model(
        model_path=args.model,
        db_path=args.db,
        journee_debut=args.journee_debut,
        journee_fin=args.journee_fin,
        n_episodes=args.episodes,
        deterministic=not args.stochastic
    )
if __name__ == "__main__":
    main()
