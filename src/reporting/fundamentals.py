"""Persistence and compact exports for fundamental analysis results."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import FundamentalAnalysisResult

SUMMARY_METRICS = (
    "revenue",
    "revenue_cagr",
    "eps_cagr",
    "ebitda_cagr",
    "fcf_cagr",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roic",
    "debt_to_equity",
    "net_debt_to_ebitda",
    "interest_coverage",
    "cash_to_debt",
    "current_ratio",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "fcf_margin",
    "fcf_per_share",
)


def fundamental_summary_frame(
    results: list[FundamentalAnalysisResult],
) -> pd.DataFrame:
    rows = []
    for result in results:
        components = result.quality_score.components
        row = {
            "ticker": result.ticker,
            "cik": result.cik,
            "company": result.company,
            "as_of": result.as_of.isoformat(),
            "latest_period_end": (
                result.latest_period_end.isoformat() if result.latest_period_end else None
            ),
            "status": result.status.value,
            "data_quality": result.data_quality.value,
            "fundamental_quality_score": result.quality_score.score,
            "fundamental_quality_observed_score": result.quality_score.observed_score,
            "score_coverage": result.quality_score.coverage,
            "growth_score": _component_value(components, "growth"),
            "profitability_score": _component_value(components, "profitability"),
            "balance_sheet_score": _component_value(components, "balance_sheet"),
            "cash_flow_score": _component_value(components, "cash_flow"),
            "error": result.error,
            "sources": json.dumps(result.sources, ensure_ascii=False),
        }
        for metric_name in SUMMARY_METRICS:
            metric = result.metrics.get(metric_name)
            row[metric_name] = metric.value if metric else None
            row[f"{metric_name}_status"] = (
                metric.status.value if metric else "data_unavailable"
            )
        rows.append(row)
    return pd.DataFrame(rows)


def persist_fundamental_results(
    results: list[FundamentalAnalysisResult],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    """Write full audit JSON per issuer and a timestamped summary CSV."""

    processed = Path(processed_dir) / "fundamentals"
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
        path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        paths.append(path)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary_path = reports / f"fundamental_analysis_{timestamp}.csv"
    fundamental_summary_frame(results).to_csv(summary_path, index=False)
    paths.append(summary_path)
    return paths


def _component_value(components, name: str) -> float | None:
    component = components.get(name)
    return component.adjusted_score if component else None
