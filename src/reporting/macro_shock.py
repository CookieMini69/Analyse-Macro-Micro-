"""Auditable JSON/CSV persistence for macro, news, and shock analysis."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import (
    MacroSeriesAnalysis,
    MacroSeriesResult,
    NewsSearchResult,
    ShockAnalysisResult,
)


def persist_macro_results(
    raw: dict[str, MacroSeriesResult],
    analyses: dict[str, MacroSeriesAnalysis],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    processed = Path(processed_dir) / "macro"
    reports = Path(report_dir)
    processed.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for key, result in raw.items():
        safe_key = _safe_name(key)
        safe_as_of = result.as_of.strftime("%Y%m%dT%H%M%SZ")
        path = processed / f"{safe_key}__asof_{safe_as_of}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
    rows = []
    for key, analysis in analyses.items():
        row = {
            "series_key": key,
            "series_id": analysis.series_id,
            "title": analysis.title,
            "as_of": analysis.as_of.isoformat(),
            "latest_value": analysis.latest_value,
            "latest_observation_date": analysis.latest_observation_date,
            "unit": analysis.unit,
            "frequency": analysis.frequency,
            "status": analysis.status.value,
            "data_quality": analysis.data_quality.value,
            "source_url": analysis.source_url,
            "error": analysis.error,
        }
        for name, metric in analysis.changes.items():
            row[name] = metric.value
            row[f"{name}_status"] = metric.status.value
        rows.append(row)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = reports / f"macro_analysis_{timestamp}.csv"
    pd.DataFrame(rows).to_csv(summary, index=False)
    paths.append(summary)
    return paths


def persist_shock_results(
    news: dict[str, NewsSearchResult],
    shocks: dict[str, ShockAnalysisResult],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    processed_news = Path(processed_dir) / "news"
    processed_shocks = Path(processed_dir) / "shocks"
    reports = Path(report_dir)
    for destination in (processed_news, processed_shocks, reports):
        destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ticker, result in news.items():
        safe = _safe_name(ticker)
        safe_as_of = result.as_of.strftime("%Y%m%dT%H%M%SZ")
        path = processed_news / f"{safe}__asof_{safe_as_of}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
    rows = []
    for ticker, result in shocks.items():
        safe = _safe_name(ticker)
        safe_as_of = result.as_of.strftime("%Y%m%dT%H%M%SZ")
        path = processed_shocks / f"{safe}__asof_{safe_as_of}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
        rows.append(
            {
                "ticker": result.ticker,
                "company": result.company,
                "as_of": result.as_of.isoformat(),
                "category": result.category.value,
                "nature": result.nature.value,
                "status": result.status.value,
                "data_quality": result.data_quality.value,
                "temporary_shock_score": result.temporary_score.score,
                "temporary_shock_observed_score": (
                    result.temporary_score.observed_score
                ),
                "score_coverage": result.temporary_score.coverage,
                "specification_criteria_coverage": (
                    result.specification_criteria_coverage
                ),
                "missing_criteria": json.dumps(
                    result.missing_criteria, ensure_ascii=False
                ),
                "evidence_count": len(result.evidence),
                "independent_source_count": result.independent_source_count,
                "macro_associations": json.dumps(
                    [item.model_dump(mode="json") for item in result.macro_associations],
                    ensure_ascii=False,
                ),
                "conclusion": result.conclusion,
                "sources": json.dumps(result.sources, ensure_ascii=False),
                "error": result.error,
            }
        )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = reports / f"shock_analysis_{timestamp}.csv"
    pd.DataFrame(rows).to_csv(summary, index=False)
    paths.append(summary)
    return paths


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)
