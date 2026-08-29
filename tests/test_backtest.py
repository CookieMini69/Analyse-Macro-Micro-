from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from src.backtest.engine import run_backtest
from src.config import BacktestSettings
from src.models import DataStatus
from src.reporting.backtest import persist_backtest_result


def backtest_fixture():
    snapshot = date(2019, 12, 31)
    tickers = ["S50", "S60", "S70", "S80", "S90"]
    signals = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "signal_date": "2020-01-02",
                "opportunity_score": score,
                "data_quality": "HIGH",
                "signal_available_at": "2020-01-02T20:00:00Z",
                "universe_snapshot_date": snapshot.isoformat(),
                "source_archive_id": f"archive-{ticker}",
                "source_archive_sha256": "a" * 64,
                "point_in_time_validated": True,
                "archive_integrity_verified": True,
                "benchmark_ticker": "BENCH",
            }
            for ticker, score in zip(tickers, [55, 65, 75, 85, 95])
        ]
    )
    dates = pd.bdate_range("2020-01-02", "2021-02-05")
    rows = []
    for index, ticker in enumerate(tickers, 1):
        values = np.linspace(100, 100 * (1 + 0.05 * index), len(dates))
        rows.extend(
            {"ticker": ticker, "observation_date": day.date(), "adjusted_close": value}
            for day, value in zip(dates, values)
        )
    rows.extend(
        {"ticker": "BENCH", "observation_date": day.date(), "adjusted_close": value}
        for day, value in zip(dates, np.linspace(100, 103, len(dates)))
    )
    return signals, pd.DataFrame(rows), {snapshot: set(tickers)}


def test_strict_backtest_uses_next_session_and_reports_all_metrics_and_buckets() -> None:
    signals, prices, snapshots = backtest_fixture()
    result = run_backtest(
        signals,
        prices,
        snapshots,
        BacktestSettings(enabled=True, minimum_trades=5),
        as_of=datetime(2021, 2, 5, tzinfo=UTC),
    )
    assert result.status == DataStatus.AVAILABLE
    assert result.validation.valid is True
    assert result.validation.look_ahead_free is True
    assert result.validation.survivorship_free is True
    assert result.validation.benchmark_data_complete is True
    assert len(result.trades) == 5
    assert all(trade.entry_date > trade.signal_date for trade in result.trades)
    assert set(result.score_buckets) == {"50-59", "60-69", "70-79", "80-89", "90-100"}
    assert result.overall.cagr is not None
    assert result.overall.total_return is not None
    assert result.overall.maximum_drawdown is not None
    assert result.overall.volatility is not None
    assert result.overall.sharpe is not None
    assert result.overall.hit_rate == 1.0
    assert result.overall.performance_vs_benchmark is not None
    assert 2020 in result.years


def test_backtest_rejects_future_signal_availability() -> None:
    signals, prices, snapshots = backtest_fixture()
    signals.loc[0, "signal_available_at"] = "2020-01-03T00:00:00Z"
    result = run_backtest(signals, prices, snapshots, BacktestSettings(enabled=True))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.validation.look_ahead_free is False
    assert "postdates" in result.error


def test_backtest_rejects_current_survivor_list_without_dated_membership() -> None:
    signals, prices, _ = backtest_fixture()
    result = run_backtest(signals, prices, {}, BacktestSettings(enabled=True))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.validation.survivorship_free is False
    assert "universe snapshots" in result.error


def test_backtest_rejects_unvalidated_reconstructed_signals() -> None:
    signals, prices, snapshots = backtest_fixture()
    signals["point_in_time_validated"] = False
    result = run_backtest(signals, prices, snapshots, BacktestSettings(enabled=True))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.validation.point_in_time_inputs is False
    assert "point_in_time_validated" in result.error


def test_backtest_rejects_missing_archive_hash() -> None:
    signals, prices, snapshots = backtest_fixture()
    signals.loc[0, "source_archive_sha256"] = "not-a-sha256"
    result = run_backtest(signals, prices, snapshots, BacktestSettings(enabled=True))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.validation.point_in_time_inputs is False
    assert "source_archive_sha256" in result.error


def test_backtest_rejects_missing_benchmark_prices() -> None:
    signals, prices, snapshots = backtest_fixture()
    prices = prices[prices["ticker"] != "BENCH"]
    result = run_backtest(signals, prices, snapshots, BacktestSettings(enabled=True))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.validation.benchmark_data_complete is False
    assert "benchmarks" in result.error


def test_backtest_persists_json_metrics_and_trades(tmp_path) -> None:
    signals, prices, snapshots = backtest_fixture()
    result = run_backtest(
        signals,
        prices,
        snapshots,
        BacktestSettings(enabled=True),
        as_of=datetime(2021, 2, 5, tzinfo=UTC),
    )
    outputs = persist_backtest_result(result, tmp_path / "phase9.json")
    assert [path.name for path in outputs] == [
        "phase9.json", "phase9_metrics.csv", "phase9_trades.csv"
    ]
    assert all(path.exists() for path in outputs)
    metrics = pd.read_csv(outputs[1])
    assert set(metrics["scope"]) == {"overall", "score_bucket", "year"}
