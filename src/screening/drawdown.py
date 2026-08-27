"""Pure price-statistic calculations with explicit missing-data statuses."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.models import DataStatus, MetricValue
from src.screening.momentum import annualized_volatility, beta, relative_strength_index


@dataclass(frozen=True, slots=True)
class PriceMetrics:
    current_price: float | None
    price_basis: str | None
    observation_date: object | None
    values: dict[str, MetricValue]


def select_price_series(frame: pd.DataFrame) -> tuple[pd.Series | None, str | None]:
    """Prefer adjusted close; disclose close as fallback rather than hiding it."""

    for column in ("adjusted_close", "close"):
        if column in frame:
            series = pd.to_numeric(frame[column], errors="coerce")
            if series.notna().any():
                dates = pd.to_datetime(frame["observation_date"], errors="coerce")
                series.index = dates
                return series.dropna().sort_index(), column
    return None, None


def _unavailable(reason: str) -> MetricValue:
    return MetricValue.unavailable(reason)


def _ratio_change(current: float, reference: float) -> MetricValue:
    if reference <= 0:
        return _unavailable("reference price is missing or non-positive")
    return MetricValue.available(current / reference - 1.0)


def trailing_return(prices: pd.Series, sessions: int) -> MetricValue:
    if len(prices) < sessions + 1:
        return _unavailable(f"requires at least {sessions + 1} price observations")
    return _ratio_change(float(prices.iloc[-1]), float(prices.iloc[-(sessions + 1)]))


def ytd_return(prices: pd.Series) -> MetricValue:
    current_date = prices.index[-1]
    prior = prices[prices.index.year < current_date.year]
    if prior.empty:
        return _unavailable("no prior year-end observation")
    return _ratio_change(float(prices.iloc[-1]), float(prior.iloc[-1]))


def distance_to_moving_average(prices: pd.Series, window: int) -> MetricValue:
    if len(prices) < window:
        return _unavailable(f"requires at least {window} price observations")
    average = float(prices.tail(window).mean())
    return _ratio_change(float(prices.iloc[-1]), average)


def relative_performance(
    asset: pd.Series, reference: pd.Series | None, sessions: int = 252
) -> MetricValue:
    if reference is None:
        return _unavailable("reference series is not configured or unavailable")
    aligned = pd.concat([asset.rename("asset"), reference.rename("reference")], axis=1).dropna()
    if len(aligned) < sessions + 1:
        return _unavailable(f"requires {sessions + 1} aligned observations")
    sample = aligned.tail(sessions + 1)
    asset_return = float(sample["asset"].iloc[-1] / sample["asset"].iloc[0] - 1)
    reference_return = float(sample["reference"].iloc[-1] / sample["reference"].iloc[0] - 1)
    return MetricValue.available(asset_return - reference_return)


def calculate_price_metrics(
    frame: pd.DataFrame,
    *,
    benchmark_frame: pd.DataFrame | None = None,
    sector_frame: pd.DataFrame | None = None,
    rsi_period: int = 14,
    annualization_days: int = 252,
) -> PriceMetrics:
    """Calculate all V1 metrics from data available through the latest row."""

    prices, basis = select_price_series(frame)
    if prices is None or prices.empty:
        names = (
            "drawdown_ath",
            "drawdown_52w",
            "drawdown_1m",
            "drawdown_3m",
            "drawdown_6m",
            "drawdown_ytd",
            "drawdown_1y",
            "distance_ma50",
            "distance_ma200",
            "rsi",
            "volatility",
            "beta",
            "relative_benchmark_performance",
            "relative_sector_performance",
        )
        return PriceMetrics(
            current_price=None,
            price_basis=None,
            observation_date=None,
            values={name: _unavailable("price data unavailable") for name in names},
        )

    benchmark_prices = select_price_series(benchmark_frame)[0] if benchmark_frame is not None else None
    sector_prices = select_price_series(sector_frame)[0] if sector_frame is not None else None
    current = float(prices.iloc[-1])
    ath = float(prices.max())
    high_52w = float(prices.tail(252).max()) if len(prices) >= 252 else None
    rsi_value = relative_strength_index(prices, rsi_period)
    volatility_value = annualized_volatility(prices, annualization_days)
    beta_value = beta(prices, benchmark_prices)

    values = {
        "drawdown_ath": _ratio_change(current, ath),
        "drawdown_52w": (
            _ratio_change(current, high_52w)
            if high_52w is not None
            else _unavailable("requires at least 252 price observations")
        ),
        "drawdown_1m": trailing_return(prices, 21),
        "drawdown_3m": trailing_return(prices, 63),
        "drawdown_6m": trailing_return(prices, 126),
        "drawdown_ytd": ytd_return(prices),
        "drawdown_1y": trailing_return(prices, 252),
        "distance_ma50": distance_to_moving_average(prices, 50),
        "distance_ma200": distance_to_moving_average(prices, 200),
        "rsi": MetricValue.available(rsi_value) if rsi_value is not None else _unavailable("insufficient observations for RSI"),
        "volatility": MetricValue.available(volatility_value) if volatility_value is not None else _unavailable("insufficient observations for volatility"),
        "beta": MetricValue.available(beta_value) if beta_value is not None else _unavailable("benchmark missing or insufficient aligned observations"),
        "relative_benchmark_performance": relative_performance(prices, benchmark_prices),
        "relative_sector_performance": relative_performance(prices, sector_prices),
    }
    observation_date = prices.index[-1].date() if hasattr(prices.index[-1], "date") else prices.index[-1]
    return PriceMetrics(
        current_price=current,
        price_basis=basis,
        observation_date=observation_date,
        values=values,
    )
