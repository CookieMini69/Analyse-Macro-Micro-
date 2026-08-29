"""Persistence for dated FX reference rates."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import FxRateResult


def persist_fx_results(results: dict[str, FxRateResult], processed_dir, report_dir) -> list[Path]:
    processed = Path(processed_dir) / "fx"
    reports = Path(report_dir)
    processed.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    rows = []
    for pair, result in results.items():
        safe = pair.replace("/", "_")
        path = processed / f"{safe}__asof_{result.as_of:%Y%m%dT%H%M%SZ}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
        observation = result.observation
        rows.append({
            "pair": pair, "as_of": result.as_of.isoformat(),
            "status": result.status.value, "data_quality": result.data_quality.value,
            "rate": observation.rate if observation else None,
            "observation_date": observation.observation_date if observation else None,
            "source": observation.source if observation else None,
            "source_url": result.source_url, "retrieved_at": result.retrieved_at.isoformat(),
            "error": result.error,
        })
    summary = reports / f"fx_analysis_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.csv"
    pd.DataFrame(rows).to_csv(summary, index=False)
    paths.append(summary)
    return paths


__all__ = ["persist_fx_results"]
