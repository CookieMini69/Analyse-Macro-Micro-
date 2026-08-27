"""Persistence and compact exports for point-in-time valuation results."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import ValuationAnalysisResult


def valuation_summary_frame(results: list[ValuationAnalysisResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        row = {
            "ticker": result.ticker,
            "company": result.company,
            "sector": result.sector,
            "as_of": result.as_of.isoformat(),
            "valuation_price": result.valuation_price,
            "valuation_price_date": result.valuation_price_date,
            "valuation_currency": result.valuation_currency,
            "market_cap": result.market_cap,
            "market_cap_basis": result.market_cap_basis,
            "status": result.status.value,
            "data_quality": result.data_quality.value,
            "valuation_score": result.score.score,
            "valuation_observed_score": result.score.observed_score,
            "score_coverage": result.score.coverage,
            "score_status": result.score.status.value,
            "reverse_dcf_implied_revenue_growth": (
                result.reverse_dcf.implied_revenue_growth
                if result.reverse_dcf is not None
                else None
            ),
            "error": result.error,
            "sources": json.dumps(result.sources, ensure_ascii=False),
        }
        for name in ("pe", "ev_ebitda", "price_fcf"):
            multiple = result.multiples.get(name)
            row[f"{name}_current"] = multiple.current.value if multiple else None
            row[f"{name}_historical_median"] = (
                multiple.historical_median.value if multiple else None
            )
            row[f"{name}_sector_median"] = (
                multiple.sector_median.value if multiple else None
            )
            row[f"{name}_history_count"] = len(multiple.history) if multiple else 0
            row[f"{name}_sector_peer_count"] = (
                multiple.sector_peer_count if multiple else 0
            )
        for scenario in ("bear", "base", "bull", "normalized"):
            item = result.dcf_scenarios.get(scenario)
            row[f"dcf_{scenario}_value_per_share"] = (
                item.value_per_share if item else None
            )
            row[f"dcf_{scenario}_status"] = (
                item.status.value if item else "not_applicable"
            )
        rows.append(row)
    return pd.DataFrame(rows)


def persist_valuation_results(
    results: list[ValuationAnalysisResult],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    """Write the full audit trail per issuer and one timestamped summary CSV."""

    processed = Path(processed_dir) / "valuations"
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
    summary_path = reports / f"valuation_analysis_{timestamp}.csv"
    valuation_summary_frame(results).to_csv(summary_path, index=False)
    paths.append(summary_path)
    return paths
