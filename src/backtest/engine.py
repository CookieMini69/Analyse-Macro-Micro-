"""Strict event-driven point-in-time backtest engine."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from src.backtest.historical_data import load_backtest_inputs
from src.backtest.metrics import calculate_performance
from src.backtest.validation import validate_backtest_inputs
from src.config import BacktestSettings, load_settings
from src.data.fundamentals import normalize_as_of
from src.models import BacktestPerformance, BacktestResult, BacktestTrade, DataQuality, DataStatus
from src.reporting.backtest import persist_backtest_result

SCORE_BUCKETS = {
    "50-59": (50.0, 60.0), "60-69": (60.0, 70.0),
    "70-79": (70.0, 80.0), "80-89": (80.0, 90.0),
    "90-100": (90.0, 100.000001),
}


def run_backtest(signals: pd.DataFrame, prices: pd.DataFrame,
                 universe_snapshots: dict[date, set[str]], settings: BacktestSettings,
                 *, as_of: datetime | None = None) -> BacktestResult:
    cutoff = normalize_as_of(as_of)
    validation = validate_backtest_inputs(signals, prices, universe_snapshots, strict=settings.strict)
    if not validation.valid:
        return _unavailable(cutoff, validation, "; ".join(validation.errors))
    signal_frame = signals.copy()
    signal_frame["signal_date"] = pd.to_datetime(signal_frame["signal_date"], utc=True).dt.date
    signal_frame["universe_snapshot_date"] = pd.to_datetime(signal_frame["universe_snapshot_date"]).dt.date
    signal_frame["opportunity_score"] = pd.to_numeric(signal_frame["opportunity_score"])
    signal_frame = signal_frame[
        signal_frame["signal_date"].map(lambda value: settings.start_year <= value.year <= settings.end_year)
        & (signal_frame["opportunity_score"] >= settings.minimum_score)
        & (signal_frame["signal_date"] <= cutoff.date())
    ]
    price_frame = prices.copy()
    price_frame["ticker"] = price_frame["ticker"].astype(str).str.upper()
    price_frame["observation_date"] = pd.to_datetime(price_frame["observation_date"]).dt.date
    price_frame["adjusted_close"] = pd.to_numeric(price_frame["adjusted_close"])
    price_frame = price_frame[price_frame["observation_date"] <= cutoff.date()].sort_values(
        ["ticker", "observation_date"]
    )
    trades: list[BacktestTrade] = []
    paths: dict[tuple[str, date], pd.Series] = {}
    benchmark_paths: dict[tuple[str, date], pd.Series] = {}
    for row in signal_frame.itertuples(index=False):
        trade, path, benchmark_path = _build_trade(row, price_frame, settings)
        if trade is not None and path is not None and benchmark_path is not None:
            trades.append(trade)
            paths[(trade.ticker, trade.signal_date)] = path
            benchmark_paths[(trade.ticker, trade.signal_date)] = benchmark_path
    if not trades:
        return _unavailable(
            cutoff, validation,
            "no eligible signal has a next-session entry and complete holding-period exit",
        )
    overall = calculate_performance(
        trades, _portfolio_returns(trades, paths),
        benchmark_daily_returns=_portfolio_returns(trades, benchmark_paths),
        annual_risk_free_rate=settings.annual_risk_free_rate,
    )
    buckets = {
        name: calculate_performance(
            selected, _portfolio_returns(selected, paths),
            benchmark_daily_returns=_portfolio_returns(selected, benchmark_paths),
            annual_risk_free_rate=settings.annual_risk_free_rate,
        )
        for name, (lower, upper) in SCORE_BUCKETS.items()
        if (selected := [trade for trade in trades if lower <= trade.score < upper])
    }
    years = {
        year: calculate_performance(
            selected, _portfolio_returns(selected, paths),
            benchmark_daily_returns=_portfolio_returns(selected, benchmark_paths),
            annual_risk_free_rate=settings.annual_risk_free_rate,
        )
        for year in range(settings.start_year, settings.end_year + 1)
        if (selected := [trade for trade in trades if trade.signal_date.year == year])
    }
    if (
        len(trades) >= max(30, settings.minimum_trades * 3)
        and all(trade.data_quality == DataQuality.HIGH for trade in trades)
    ):
        quality = DataQuality.HIGH
    else:
        quality = (
            DataQuality.MEDIUM
            if len(trades) >= settings.minimum_trades else DataQuality.LOW
        )
    return BacktestResult(
        as_of=cutoff, status=DataStatus.AVAILABLE, data_quality=quality,
        validation=validation, overall=overall, score_buckets=buckets, years=years,
        trades=trades, retrieved_at=datetime.now(UTC),
    )


def _build_trade(row, prices: pd.DataFrame, settings: BacktestSettings):
    ticker = str(row.ticker).upper()
    security = prices[prices["ticker"] == ticker]
    entry_rows = security[security["observation_date"] > row.signal_date]
    if entry_rows.empty:
        return None, None, None
    entry = entry_rows.iloc[0]
    target = (pd.Timestamp(row.signal_date) + pd.DateOffset(months=settings.holding_months)).date()
    exit_rows = security[security["observation_date"] >= target]
    if exit_rows.empty:
        return None, None, None
    exit_row = exit_rows.iloc[0]
    entry_price, exit_price = float(entry["adjusted_close"]), float(exit_row["adjusted_close"])
    cost = settings.transaction_cost_bps_per_side / 10_000
    total_return = exit_price * (1 - cost) / (entry_price * (1 + cost)) - 1
    benchmark_ticker = str(row.benchmark_ticker).upper()
    benchmark_return, benchmark_path = _benchmark_path(
        prices, benchmark_ticker, entry["observation_date"], exit_row["observation_date"]
    )
    if benchmark_return is None or benchmark_path is None:
        return None, None, None
    path_frame = security[
        (security["observation_date"] >= entry["observation_date"])
        & (security["observation_date"] <= exit_row["observation_date"])
    ]
    path = pd.Series(
        path_frame["adjusted_close"].to_numpy(),
        index=pd.to_datetime(path_frame["observation_date"]), dtype=float,
    ).pct_change().fillna(0.0)
    if not path.empty:
        path.iloc[0] = 1 / (1 + cost) - 1
        path.iloc[-1] = (1 + path.iloc[-1]) * (1 - cost) - 1
    recovery = _recovery_time(path_frame, entry_price)
    quality = DataQuality(str(row.data_quality).upper())
    trade = BacktestTrade(
        ticker=ticker, signal_date=row.signal_date,
        entry_date=entry["observation_date"], exit_date=exit_row["observation_date"],
        score=float(row.opportunity_score), score_bucket=_bucket(float(row.opportunity_score)),
        data_quality=quality, entry_price=entry_price, exit_price=exit_price,
        total_return=total_return, benchmark_ticker=benchmark_ticker,
        benchmark_return=benchmark_return,
        excess_return=total_return - benchmark_return if benchmark_return is not None else None,
        recovery_time_days=recovery, universe_snapshot_date=row.universe_snapshot_date,
        source_archive_id=str(row.source_archive_id),
        source_archive_sha256=str(row.source_archive_sha256).lower(),
    )
    return trade, path, benchmark_path


def _benchmark_path(prices, ticker, entry_date, exit_date):
    frame = prices[prices["ticker"] == ticker]
    entry = frame[frame["observation_date"] >= entry_date]
    exit_rows = frame[frame["observation_date"] >= exit_date]
    if entry.empty or exit_rows.empty:
        return None, None
    start_date = entry.iloc[0]["observation_date"]
    end_date = exit_rows.iloc[0]["observation_date"]
    path_frame = frame[
        (frame["observation_date"] >= start_date)
        & (frame["observation_date"] <= end_date)
    ]
    if path_frame.empty:
        return None, None
    total_return = (
        float(path_frame.iloc[-1]["adjusted_close"])
        / float(path_frame.iloc[0]["adjusted_close"])
        - 1
    )
    path = pd.Series(
        path_frame["adjusted_close"].to_numpy(),
        index=pd.to_datetime(path_frame["observation_date"]),
        dtype=float,
    ).pct_change().fillna(0.0)
    return total_return, path


def _recovery_time(path: pd.DataFrame, entry_price: float) -> int | None:
    below = path[path["adjusted_close"] < entry_price]
    if below.empty:
        return 0
    first = below.iloc[0]["observation_date"]
    recovered = path[(path["observation_date"] > first) & (path["adjusted_close"] >= entry_price)]
    return (recovered.iloc[0]["observation_date"] - first).days if not recovered.empty else None


def _portfolio_returns(trades, paths) -> pd.Series:
    series = [paths[(trade.ticker, trade.signal_date)].rename(index) for index, trade in enumerate(trades)]
    if not series:
        return pd.Series(dtype=float)
    combined = pd.concat(series, axis=1).mean(axis=1, skipna=True)
    calendar = pd.bdate_range(combined.index.min(), combined.index.max())
    return combined.reindex(calendar).fillna(0.0)


def _bucket(score: float) -> str:
    for name, (lower, upper) in SCORE_BUCKETS.items():
        if lower <= score < upper:
            return name
    return "below-50"


def _unavailable(cutoff, validation, error):
    return BacktestResult(
        as_of=cutoff, status=DataStatus.DATA_UNAVAILABLE,
        data_quality=DataQuality.UNAVAILABLE, validation=validation,
        overall=BacktestPerformance(trade_count=0), retrieved_at=datetime.now(UTC),
        error=error,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the strict point-in-time Phase 9 backtest")
    parser.add_argument("--signals", required=True)
    parser.add_argument("--prices", required=True)
    parser.add_argument("--universes", required=True)
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--output", default="reports/backtest_result.json")
    args = parser.parse_args()
    signals, prices, snapshots = load_backtest_inputs(args.signals, args.prices, args.universes)
    settings = load_settings(args.config).backtest
    result = run_backtest(signals, prices, snapshots, settings, as_of=args.as_of)
    outputs = persist_backtest_result(result, Path(args.output))
    for output in outputs:
        print(output)
    return 0 if result.status == DataStatus.AVAILABLE else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SCORE_BUCKETS", "run_backtest"]
