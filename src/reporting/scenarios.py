"""Auditable persistence for Phase 7 scenarios, targets, and risk/reward."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import ScenarioAnalysisResult


def scenario_summary_frame(results: list[ScenarioAnalysisResult]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for result in results:
        common = {
            "ticker": result.ticker,
            "company": result.company,
            "as_of": result.as_of.isoformat(),
            "status": result.status.value,
            "data_quality": result.data_quality.value,
            "fair_value": result.targets.fair_value.value,
            "normalized_fair_value": result.targets.normalized_fair_value.value,
            "bear_target": result.targets.bear_target.value,
            "base_target": result.targets.base_target.value,
            "bull_target": result.targets.bull_target.value,
            "tp1": result.targets.tp1.value,
            "tp2": result.targets.tp2.value,
            "tp3": result.targets.tp3.value,
            "upside_base": result.risk_reward.upside_base.value,
            "upside_bull": result.risk_reward.upside_bull.value,
            "downside_bear": result.risk_reward.downside_bear.value,
            "risk_reward": result.risk_reward.risk_reward.value,
            "invalidation_levels": json.dumps(
                [item.model_dump(mode="json") for item in result.invalidation_levels],
                ensure_ascii=False,
            ),
            "missing_invalidation_dimensions": json.dumps(
                result.missing_invalidation_dimensions, ensure_ascii=False
            ),
            "error": result.error,
        }
        if not result.cases:
            rows.append(common)
            continue
        for case in result.cases.values():
            for horizon in case.horizons:
                rows.append(
                    {
                        **common,
                        "scenario": case.scenario,
                        "statistic": case.statistic,
                        "assumption_coverage": case.assumption_coverage,
                        "months": horizon.months,
                        "projected_revenue": horizon.revenue.value,
                        "projected_operating_margin": horizon.operating_margin.value,
                        "projected_eps": horizon.eps.value,
                        "projected_free_cash_flow": horizon.free_cash_flow.value,
                        "pe_model_value": _model_value(horizon, "pe"),
                        "ev_ebitda_model_value": _model_value(horizon, "ev_ebitda"),
                        "price_fcf_model_value": _model_value(horizon, "price_fcf"),
                        "target_price": horizon.target_price.value,
                        "target_status": horizon.target_price.status.value,
                        "assumptions": json.dumps(
                            {
                                name: assumption.model_dump(mode="json")
                                for name, assumption in case.assumptions.items()
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
    return pd.DataFrame(rows)


def persist_scenario_results(
    results: list[ScenarioAnalysisResult],
    processed_dir: str | Path,
    report_dir: str | Path,
) -> list[Path]:
    processed = Path(processed_dir) / "scenarios"
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
    summary = reports / f"scenario_analysis_{timestamp}.csv"
    scenario_summary_frame(results).to_csv(summary, index=False)
    paths.append(summary)
    return paths


def _model_value(horizon, name: str) -> float | None:
    metric = horizon.model_values.get(name)
    return metric.value if metric is not None else None


__all__ = ["persist_scenario_results", "scenario_summary_frame"]
