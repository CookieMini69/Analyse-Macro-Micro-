"""Auditable persistence for Phase 8 sub-scores and opportunity scores."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import ScoringAnalysisResult


def scoring_summary_frame(results: list[ScoringAnalysisResult]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for result in results:
        rows.append(
            {
                "ticker": result.ticker,
                "company": result.company,
                "as_of": result.as_of.isoformat(),
                "status": result.status.value,
                "data_quality": result.data_quality.value,
                "fundamental_quality_score": result.fundamental_quality.score,
                "valuation_score": result.valuation.score,
                "temporary_shock_score": result.temporary_shock.score,
                "normalization_score": result.normalization.score,
                "catalyst_score": result.catalyst.score,
                "future_growth_score": result.future_growth.score,
                "risk_score": result.risk.score,
                "risk_score_direction": "higher means lower measured risk",
                "opportunity_score": result.opportunity.score,
                "opportunity_observed_score": result.opportunity.observed_score,
                "opportunity_score_coverage": result.opportunity.coverage,
                "confidence_score": result.confidence_score,
                "score_band": result.score_band,
                "interpretation": result.opportunity.interpretation,
                "subscores": json.dumps(
                    {
                        "fundamental_quality": result.fundamental_quality.model_dump(mode="json"),
                        "valuation": result.valuation.model_dump(mode="json"),
                        "temporary_shock": result.temporary_shock.model_dump(mode="json"),
                        "normalization": result.normalization.model_dump(mode="json"),
                        "catalyst": result.catalyst.model_dump(mode="json"),
                        "future_growth": result.future_growth.model_dump(mode="json"),
                        "risk": result.risk.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
                "opportunity_components": json.dumps(
                    {
                        name: component.model_dump(mode="json")
                        for name, component in result.opportunity.components.items()
                    },
                    ensure_ascii=False,
                ),
                "sources": json.dumps(result.sources, ensure_ascii=False),
                "retrieved_at": result.retrieved_at.isoformat(),
                "error": result.error,
            }
        )
    return pd.DataFrame(rows)


def persist_scoring_results(
    results: list[ScoringAnalysisResult],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    processed = Path(processed_dir) / "scoring"
    reports = Path(report_dir)
    processed.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for result in results:
        ticker = re.sub(r"[^A-Za-z0-9._-]+", "_", result.ticker)
        as_of = result.as_of.strftime("%Y%m%dT%H%M%SZ")
        retrieved = result.retrieved_at.strftime("%Y%m%dT%H%M%SZ")
        path = processed / f"{ticker}__asof_{as_of}__retrieved_{retrieved}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        paths.append(path)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = reports / f"opportunity_scoring_{timestamp}.csv"
    scoring_summary_frame(results).to_csv(summary, index=False)
    paths.append(summary)
    return paths


__all__ = ["persist_scoring_results", "scoring_summary_frame"]
