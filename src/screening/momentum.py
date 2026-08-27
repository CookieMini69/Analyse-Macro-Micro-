"""Technical statistics used by the V1 price scanner."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _numeric_series(values: pd.Series | np.ndarray) -> pd.Series:
    """Normalize array-like numeric inputs without inventing missing values."""

    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce").dropna()
    return pd.to_numeric(pd.Series(values), errors="coerce").dropna()


def relative_strength_index(
    prices: pd.Series | np.ndarray, period: int = 14
) -> float | None:
    """Return Wilder's RSI for the most recent observation."""

    clean = _numeric_series(prices)
    if len(clean) < period + 1:
        return None
    changes = clean.diff()
    gains = changes.clip(lower=0)
    losses = -changes.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    last_gain = float(average_gain.iloc[-1])
    last_loss = float(average_loss.iloc[-1])
    if np.isnan(last_gain) or np.isnan(last_loss):
        return None
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0
    relative_strength = last_gain / last_loss
    return float(100 - (100 / (1 + relative_strength)))


def annualized_volatility(
    prices: pd.Series | np.ndarray, annualization_days: int = 252
) -> float | None:
    clean = _numeric_series(prices)
    returns = clean.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2:
        return None
    return float(returns.std(ddof=1) * np.sqrt(annualization_days))


def beta(prices: pd.Series, benchmark: pd.Series | None) -> float | None:
    """Calculate beta from aligned daily returns over at most 252 sessions."""

    if benchmark is None:
        return None
    aligned = pd.concat(
        [
            pd.to_numeric(prices, errors="coerce").rename("asset"),
            pd.to_numeric(benchmark, errors="coerce").rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    returns = aligned.pct_change().replace([np.inf, -np.inf], np.nan).dropna().tail(252)
    if len(returns) < 20:
        return None
    benchmark_variance = float(returns["benchmark"].var(ddof=1))
    if benchmark_variance == 0 or np.isnan(benchmark_variance):
        return None
    covariance = float(returns["asset"].cov(returns["benchmark"]))
    return covariance / benchmark_variance
