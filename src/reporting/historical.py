"""Auditable JSON and CSV persistence for historical analogues."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import HistoricalAnalogueResult


def historical_summary_frame(results: list[HistoricalAnalogueResult]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for result in results:
        current = result.current_episode
        if not result.analogues:
            rows.append(
                {
                    "ticker": result.ticker,
                    "company": result.company,
                    "as_of": result.as_of.isoformat(),
                    "status": result.status.value,
                    "data_quality": result.data_quality.value,
                    "current_peak_date": current.peak_date if current else None,
                    "current_maximum_drawdown": (
                        current.maximum_drawdown if current else None
                    ),
                    "completed_episode_count": result.detected_completed_episode_count,
                    "error": result.error,
                }
            )
            continue
        for rank, analogue in enumerate(result.analogues, start=1):
            episode = analogue.episode
            row = {
                "ticker": result.ticker,
                "company": result.company,
                "as_of": result.as_of.isoformat(),
                "status": result.status.value,
                "data_quality": result.data_quality.value,
                "analogue_rank": rank,
                "similarity_score": analogue.similarity_score,
                "similarity_coverage": analogue.similarity_coverage,
                "similarity_components": json.dumps(
                    {
                        name: metric.model_dump(mode="json")
                        for name, metric in analogue.similarity_components.items()
                    },
                    ensure_ascii=False,
                ),
                "current_peak_date": current.peak_date if current else None,
                "current_trough_date": current.trough_date if current else None,
                "current_maximum_drawdown": (
                    current.maximum_drawdown if current else None
                ),
                "current_decline_duration_days": (
                    current.decline_duration_days if current else None
                ),
                "historical_peak_date": episode.peak_date,
                "historical_trough_date": episode.trough_date,
                "historical_recovery_date": episode.recovery_date,
                "historical_maximum_drawdown": episode.maximum_drawdown,
                "historical_decline_duration_days": episode.decline_duration_days,
                "historical_recovery_duration_days": episode.recovery_duration_days,
                "historical_total_recovery_days": episode.total_recovery_days,
                "historical_fundamentals": json.dumps(
                    episode.fundamentals.model_dump(mode="json")
                    if episode.fundamentals else None,
                    ensure_ascii=False,
                ),
                "historical_valuation": json.dumps(
                    episode.valuation.model_dump(mode="json")
                    if episode.valuation else None,
                    ensure_ascii=False,
                ),
                "completed_episode_count": result.detected_completed_episode_count,
                "error": result.error,
            }
            for name, metric in episode.subsequent_returns.items():
                row[name] = metric.value
                row[f"{name}_status"] = metric.status.value
            rows.append(row)
    return pd.DataFrame(rows)


def persist_historical_results(
    results: list[HistoricalAnalogueResult],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    """Write full cutoff-versioned JSON per issuer and one comparison CSV."""

    processed = Path(processed_dir) / "historical"
    reports = Path(report_dir)
    processed.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for result in results:
        safe_ticker = re.sub(r"[^A-Za-z0-9._-]+", "_", result.ticker)
        safe_as_of = result.as_of.strftime("%Y%m%dT%H%M%SZ")
        safe_retrieved = result.retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        path = processed / (
            f"{safe_ticker}__asof_{safe_as_of}__retrieved_{safe_retrieved}.json"
        )
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = reports / f"historical_analogues_{timestamp}.csv"
    historical_summary_frame(results).to_csv(summary, index=False)
    paths.append(summary)
    return paths


__all__ = ["historical_summary_frame", "persist_historical_results"]
