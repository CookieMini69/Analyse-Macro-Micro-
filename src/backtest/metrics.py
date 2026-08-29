"""Performance statistics for strict point-in-time backtest trades."""

from __future__ import annotations

import math
from statistics import median

import pandas as pd

from src.models import BacktestPerformance, BacktestTrade


def calculate_performance(
    trades: list[BacktestTrade],
    daily_returns: pd.Series | None = None,
    *,
    benchmark_daily_returns: pd.Series | None = None,
    annual_risk_free_rate: float = 0.0,
) -> BacktestPerformance:
    if not trades:
        return BacktestPerformance(trade_count=0)
    returns = [trade.total_return for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    series = (
        daily_returns.dropna().sort_index()
        if daily_returns is not None else pd.Series(dtype=float)
    )
    benchmark_series = (
        benchmark_daily_returns.dropna().sort_index()
        if benchmark_daily_returns is not None else pd.Series(dtype=float)
    )
    total_return = float((1 + series).prod() - 1) if not series.empty else None
    start = min(trade.entry_date for trade in trades)
    end = max(trade.exit_date for trade in trades)
    years = max((end - start).days / 365.25, 1 / 365.25)
    cagr = (
        (1 + total_return) ** (1 / years) - 1
        if total_return is not None and total_return > -1 else None
    )
    volatility = float(series.std(ddof=1) * math.sqrt(252)) if len(series) > 1 else None
    annual_return = float(series.mean() * 252) if not series.empty else None
    sharpe = (
        (annual_return - annual_risk_free_rate) / volatility
        if annual_return is not None and volatility not in {None, 0.0} else None
    )
    downside = series[series < 0]
    downside_deviation = (
        float(downside.std(ddof=1) * math.sqrt(252)) if len(downside) > 1 else None
    )
    sortino = (
        (annual_return - annual_risk_free_rate) / downside_deviation
        if annual_return is not None and downside_deviation not in {None, 0.0}
        else None
    )
    max_drawdown, recovery_days = _drawdown_metrics(series)
    benchmark_total = (
        float((1 + benchmark_series).prod() - 1)
        if not benchmark_series.empty else None
    )
    average_return = sum(returns) / len(returns)
    return BacktestPerformance(
        trade_count=len(trades),
        start_date=start,
        end_date=end,
        cagr=cagr,
        total_return=total_return,
        hit_rate=len(wins) / len(returns),
        average_return=average_return,
        median_return=median(returns),
        maximum_drawdown=max_drawdown,
        volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        recovery_time_days=recovery_days,
        win_loss_ratio=(
            (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
            if wins and losses else None
        ),
        benchmark_return=benchmark_total,
        performance_vs_benchmark=(
            total_return - benchmark_total
            if total_return is not None and benchmark_total is not None else None
        ),
    )


def _drawdown_metrics(returns: pd.Series) -> tuple[float | None, int | None]:
    if returns.empty:
        return None, None
    equity = (1 + returns).cumprod()
    running_peak = equity.cummax()
    drawdown = equity / running_peak - 1
    maximum = float(drawdown.min())
    longest = 0
    peak_date = equity.index[0]
    for index, value in drawdown.items():
        if value >= 0:
            peak_date = index
        else:
            longest = max(longest, (index - peak_date).days)
    return maximum, longest


__all__ = ["calculate_performance"]
