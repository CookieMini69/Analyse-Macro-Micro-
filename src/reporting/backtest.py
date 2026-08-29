"""Auditable JSON and CSV exports for Phase 9 backtests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.models import BacktestPerformance, BacktestResult


def persist_backtest_result(
    result: BacktestResult,
    output_path: str | Path,
) -> list[Path]:
    output = Path(output_path)
    if output.suffix.lower() != ".json":
        output = output / "backtest_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    stem = output.with_suffix("")
    metrics_path = stem.with_name(f"{stem.name}_metrics.csv")
    trades_path = stem.with_name(f"{stem.name}_trades.csv")
    metric_rows = [_performance_row("overall", "all", result.overall)]
    metric_rows.extend(
        _performance_row("score_bucket", name, performance)
        for name, performance in result.score_buckets.items()
    )
    metric_rows.extend(
        _performance_row("year", str(year), performance)
        for year, performance in result.years.items()
    )
    pd.DataFrame(metric_rows).to_csv(metrics_path, index=False)
    pd.DataFrame(
        [trade.model_dump(mode="json") for trade in result.trades]
    ).to_csv(trades_path, index=False)
    return [output, metrics_path, trades_path]


def _performance_row(
    scope: str,
    label: str,
    performance: BacktestPerformance,
) -> dict:
    return {"scope": scope, "label": label, **performance.model_dump(mode="json")}


__all__ = ["persist_backtest_result"]
