"""Model-derived target and risk/reward calculations."""

from __future__ import annotations

from statistics import median

from src.models import (
    DataStatus,
    MetricValue,
    RiskRewardResult,
    ScenarioCaseResult,
    ScenarioTargetSummary,
    ValuationAnalysisResult,
)


def aggregate_model_values(
    values: dict[str, MetricValue], *, minimum_models: int
) -> MetricValue:
    """Use the median available model value; never add a discretionary premium."""

    observed = [
        metric.value
        for metric in values.values()
        if metric.status == DataStatus.AVAILABLE
        and metric.value is not None
        and metric.value > 0
    ]
    if len(observed) < minimum_models:
        return MetricValue.unavailable(
            f"{len(observed)} target models available; {minimum_models} required"
        )
    return MetricValue.available(median(observed))


def build_target_summary(
    cases: dict[str, ScenarioCaseResult],
    valuation: ValuationAnalysisResult | None,
    *,
    target_horizon_months: int,
) -> ScenarioTargetSummary:
    bear = _case_target(cases.get("bear"))
    base = _case_target(cases.get("base"))
    bull = _case_target(cases.get("bull"))
    fair_value = _dcf_value(valuation, "base")
    if fair_value.value is None:
        fair_value = base
    normalized = _dcf_value(valuation, "normalized")
    return ScenarioTargetSummary(
        fair_value=fair_value,
        normalized_fair_value=normalized,
        bear_target=bear,
        base_target=base,
        bull_target=bull,
        tp1=_horizon_target(cases.get("base"), 6),
        tp2=_horizon_target(cases.get("base"), 12),
        tp3=_horizon_target(cases.get("base"), 24),
        target_horizon_months=target_horizon_months,
        methodology=(
            "fair value uses sourced base DCF when available, otherwise the "
            "base temporal target; normalized fair value requires a sourced "
            "normalized DCF and otherwise remains unavailable; TP1/TP2/TP3 "
            "are the 6/12/24-month base targets"
        ),
    )


def calculate_risk_reward(
    current_price: float | None, targets: ScenarioTargetSummary
) -> RiskRewardResult:
    if current_price is None or current_price <= 0:
        reason = "positive current price is unavailable"
        unavailable = MetricValue.unavailable(reason)
        return RiskRewardResult(
            current_price=None,
            upside_base=unavailable,
            upside_bull=unavailable,
            downside_bear=unavailable,
            risk_reward=unavailable,
        )
    base = _return_metric(targets.base_target, current_price)
    bull = _return_metric(targets.bull_target, current_price)
    bear = _return_metric(targets.bear_target, current_price)
    if (
        base.value is None
        or bear.value is None
        or base.value <= 0
        or bear.value >= 0
    ):
        ratio = MetricValue.unavailable(
            "risk/reward requires positive base upside and negative bear downside"
        )
    else:
        ratio = MetricValue.available(base.value / abs(bear.value))
    return RiskRewardResult(
        current_price=current_price,
        upside_base=base,
        upside_bull=bull,
        downside_bear=bear,
        risk_reward=ratio,
    )


def _case_target(case: ScenarioCaseResult | None) -> MetricValue:
    return (
        case.target_price
        if case is not None
        else MetricValue.unavailable("scenario case is unavailable")
    )


def _horizon_target(case: ScenarioCaseResult | None, months: int) -> MetricValue:
    if case is None:
        return MetricValue.unavailable("base scenario is unavailable")
    point = next((item for item in case.horizons if item.months == months), None)
    return (
        point.target_price
        if point is not None
        else MetricValue.unavailable(f"{months}-month horizon is not configured")
    )


def _dcf_value(
    valuation: ValuationAnalysisResult | None, name: str
) -> MetricValue:
    scenario = valuation.dcf_scenarios.get(name) if valuation is not None else None
    if (
        scenario is None
        or scenario.status != DataStatus.AVAILABLE
        or scenario.value_per_share is None
    ):
        return MetricValue.unavailable(f"sourced {name} DCF is unavailable")
    return MetricValue.available(scenario.value_per_share)


def _return_metric(target: MetricValue, current: float) -> MetricValue:
    if target.value is None:
        return MetricValue.unavailable(target.reason or "target is unavailable")
    return MetricValue.available(target.value / current - 1)


__all__ = ["aggregate_model_values", "build_target_summary", "calculate_risk_reward"]
