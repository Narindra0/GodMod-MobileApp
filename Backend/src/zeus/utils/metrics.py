from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass(frozen=True)
class PerformanceInput:
    capital_initial: float
    capital_final: float
    capital_history: List[float]
    total_matches: int
    total_paris: int
    paris_gagnants: int


def calculate_roi(capital_initial: float, capital_final: float) -> float:
    if capital_initial == 0:
        return 0.0
    return ((capital_final - capital_initial) / capital_initial) * 100


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    if len(returns) == 0:
        return 0.0
    returns_array = np.array(returns)
    mean_return = np.mean(returns_array)
    std_return = np.std(returns_array)
    if std_return == 0:
        return 0.0
    return (mean_return - risk_free_rate) / std_return


def calculate_max_drawdown(capital_history: List[float]) -> float:
    if len(capital_history) == 0:
        return 0.0
    capital_array = np.array(capital_history)
    peak = np.maximum.accumulate(capital_array)
    drawdown = (capital_array - peak) / peak
    max_dd = np.min(drawdown) * 100
    return max_dd


def calculate_win_rate(total_paris: int, paris_gagnants: int) -> float:
    if total_paris == 0:
        return 0.0
    return (paris_gagnants / total_paris) * 100


def calculate_abstention_rate(total_matches: int, total_paris: int) -> float:
    if total_matches == 0:
        return 0.0
    abstentions = total_matches - total_paris
    return (abstentions / total_matches) * 100


def generer_rapport_performance(input_data: PerformanceInput) -> dict:
    returns = []
    for i in range(1, len(input_data.capital_history)):
        if input_data.capital_history[i - 1] > 0:
            ret = (input_data.capital_history[i] - input_data.capital_history[i - 1]) / input_data.capital_history[
                i - 1
            ]
            returns.append(ret)
    rapport = {
        "capital_initial": input_data.capital_initial,
        "capital_final": input_data.capital_final,
        "profit_total": input_data.capital_final - input_data.capital_initial,
        "roi_percent": calculate_roi(input_data.capital_initial, input_data.capital_final),
        "win_rate_percent": calculate_win_rate(input_data.total_paris, input_data.paris_gagnants),
        "sharpe_ratio": calculate_sharpe_ratio(returns),
        "max_drawdown_percent": calculate_max_drawdown(input_data.capital_history),
        "abstention_rate_percent": calculate_abstention_rate(input_data.total_matches, input_data.total_paris),
        "total_matches": input_data.total_matches,
        "total_paris": input_data.total_paris,
        "paris_gagnants": input_data.paris_gagnants,
        "paris_perdants": input_data.total_paris - input_data.paris_gagnants,
    }
    return rapport


def afficher_rapport(rapport: dict):
    print("\n" + "=" * 60)
    print("📊 RAPPORT DE PERFORMANCE ZEUS")
    print("=" * 60)
    print("\n💰 CAPITAL")
    print(f"   Initial:     {rapport['capital_initial']:,.0f} Ar")
    print(f"   Final:       {rapport['capital_final']:,.0f} Ar")
    print(f"   Profit:      {rapport['profit_total']:+,.0f} Ar")
    print("\n📈 RENDEMENT")
    print(f"   ROI:         {rapport['roi_percent']:+.2f}%")
    print(f"   Sharpe:      {rapport['sharpe_ratio']:.3f}")
    print(f"   Max DD:      {rapport['max_drawdown_percent']:.2f}%")
    print(f"\n🎯 PARIS")
    print(f"   Matchs:      {rapport['total_matches']}")
    print(f"   Paris:       {rapport['total_paris']}")
    print(f"   Gagnés:      {rapport['paris_gagnants']}")
    print(f"   Perdus:      {rapport['paris_perdants']}")
    print(f"   Win Rate:    {rapport['win_rate_percent']:.2f}%")
    print(f"   Abstention:  {rapport['abstention_rate_percent']:.2f}%")
    print("=" * 60)
