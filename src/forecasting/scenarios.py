"""Evidence-derived bear/base/bull temporal scenario engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from statistics import median

from src.config import ScenarioSettings
from src.forecasting.targets import (
    aggregate_model_values,
    build_target_summary,
    calculate_risk_reward,
)
from src.models import (
    DataQuality,
    DataStatus,
    FundamentalAnalysisResult,
    FundamentalInvalidationLevel,
    FundamentalObservation,
    MetricValue,
    ScenarioAnalysisResult,
    ScenarioAssumption,
    ScenarioCaseResult,
    ScenarioHorizonProjection,
    Security,
    ValuationAnalysisResult,
)

SCENARIO_STATISTICS = {
    "bear": "lower_quartile",
    "base": "median",
    "bull": "upper_quartile",
}
CORE_COVERAGE_DIMENSIONS = (
    "revenue_growth",
    "margin",
    "eps",
    "free_cash_flow",
    "multiple",
    "wacc",
    "terminal_growth",
)


@dataclass(slots=True)
class EvidenceSeries:
    values: list[float] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    accessions: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    derivation: str = ""
    unit: str = "ratio"


def analyze_scenarios(
    security: Security,
    fundamental: FundamentalAnalysisResult | None,
    valuation: ValuationAnalysisResult | None,
    current_price: float | None,
    settings: ScenarioSettings,
    *,
    as_of: datetime,
) -> ScenarioAnalysisResult:
    """Build model-derived cases without discretionary percentage targets."""

    retrieved_at = datetime.now(UTC)
    if fundamental is None or fundamental.status != DataStatus.AVAILABLE:
        return _unavailable_result(
            security,
            valuation,
            current_price,
            as_of,
            retrieved_at,
            settings.target_horizon_months,
            "point-in-time fundamental history is unavailable",
        )
    retrieved_at = max(retrieved_at, fundamental.retrieved_at)
    if valuation is not None:
        retrieved_at = max(retrieved_at, valuation.retrieved_at)

    evidence = _build_evidence(fundamental, valuation)
    cases = {
        name: _build_case(
            name,
            evidence,
            fundamental,
            valuation,
            settings,
            as_of,
        )
        for name in ("bear", "base", "bull")
    }
    targets = build_target_summary(
        cases,
        valuation,
        target_horizon_months=settings.target_horizon_months,
    )
    risk_reward = calculate_risk_reward(current_price, targets)
    invalidation_levels, missing_dimensions = _invalidation_levels(cases.get("bear"))
    available_cases = [case for case in cases.values() if case.status == DataStatus.AVAILABLE]
    status = DataStatus.AVAILABLE if available_cases else DataStatus.DATA_UNAVAILABLE
    average_coverage = (
        sum(case.assumption_coverage for case in cases.values()) / len(cases)
        if cases
        else 0.0
    )
    quality = DataQuality.UNAVAILABLE
    if status == DataStatus.AVAILABLE:
        quality = (
            DataQuality.MEDIUM
            if fundamental.data_quality in {DataQuality.HIGH, DataQuality.MEDIUM}
            and valuation is not None
            and valuation.data_quality in {DataQuality.HIGH, DataQuality.MEDIUM}
            and average_coverage >= 0.70
            else DataQuality.LOW
        )
    return ScenarioAnalysisResult(
        ticker=security.ticker,
        company=security.company,
        as_of=as_of,
        status=status,
        data_quality=quality,
        cases=cases,
        targets=targets,
        risk_reward=risk_reward,
        invalidation_levels=invalidation_levels,
        missing_invalidation_dimensions=missing_dimensions,
        sources=_scenario_sources(fundamental, valuation),
        retrieved_at=retrieved_at,
        error=(
            None
            if status == DataStatus.AVAILABLE
            else "no scenario produced a model-derived target at the configured horizon"
        ),
    )


def _build_case(
    scenario: str,
    evidence: dict[str, EvidenceSeries],
    fundamental: FundamentalAnalysisResult,
    valuation: ValuationAnalysisResult | None,
    settings: ScenarioSettings,
    as_of: datetime,
) -> ScenarioCaseResult:
    statistic = SCENARIO_STATISTICS[scenario]
    assumptions = {
        name: _series_assumption(
            name,
            series,
            statistic,
            settings.minimum_history_points,
            adverse_high=(name in {"net_debt_to_ebitda"}),
        )
        for name, series in evidence.items()
    }
    for name in ("revenue", "diluted_shares", "debt", "cash"):
        assumptions[name] = _latest_metric_assumption(fundamental, name)
    assumptions["wacc"] = _dcf_assumption(
        valuation, scenario, "wacc", as_of
    )
    assumptions["terminal_growth"] = _dcf_assumption(
        valuation, scenario, "terminal_growth", as_of
    )
    coverage = _assumption_coverage(assumptions)
    horizons = [
        _project_horizon(months, assumptions, settings.minimum_target_models)
        for months in settings.horizons_months
    ]
    target_point = next(
        (item for item in horizons if item.months == settings.target_horizon_months),
        None,
    )
    target = (
        target_point.target_price
        if target_point is not None
        else MetricValue.unavailable("configured target horizon was not projected")
    )
    return ScenarioCaseResult(
        scenario=scenario,
        status=(
            DataStatus.AVAILABLE
            if target.status == DataStatus.AVAILABLE
            else DataStatus.DATA_UNAVAILABLE
        ),
        statistic=statistic,
        assumptions=assumptions,
        assumption_coverage=coverage,
        horizons=horizons,
        target_price=target,
        reason=(
            None
            if target.status == DataStatus.AVAILABLE
            else target.reason
        ),
    )


def _project_horizon(
    months: int,
    assumptions: dict[str, ScenarioAssumption],
    minimum_target_models: int,
) -> ScenarioHorizonProjection:
    revenue = _compound_revenue(months, assumptions)
    operating_margin = _metric_from_assumption(
        assumptions.get("operating_margin"), "operating margin is unavailable"
    )
    eps = _project_per_share(
        revenue,
        assumptions.get("net_margin"),
        assumptions.get("diluted_shares"),
        label="EPS",
    )
    fcf = _project_amount(
        revenue,
        assumptions.get("fcf_margin"),
        label="free cash flow",
    )
    model_values = {
        "pe": _pe_value(eps, assumptions.get("pe_multiple")),
        "price_fcf": _price_fcf_value(
            fcf,
            assumptions.get("diluted_shares"),
            assumptions.get("price_fcf_multiple"),
        ),
        "ev_ebitda": _ev_ebitda_value(revenue, assumptions),
    }
    return ScenarioHorizonProjection(
        months=months,
        revenue=revenue,
        operating_margin=operating_margin,
        eps=eps,
        free_cash_flow=fcf,
        model_values=model_values,
        target_price=aggregate_model_values(
            model_values, minimum_models=minimum_target_models
        ),
    )


def _build_evidence(
    fundamental: FundamentalAnalysisResult,
    valuation: ValuationAnalysisResult | None,
) -> dict[str, EvidenceSeries]:
    observations = fundamental.annual_observations
    evidence = {
        "revenue_growth": _growth_series(observations.get("revenue", [])),
        "operating_margin": _ratio_series(
            observations, "operating_income", "revenue", "operating income / revenue"
        ),
        "net_margin": _ratio_series(
            observations, "net_income", "revenue", "net income / revenue"
        ),
        "ebitda_margin": _ebitda_margin_series(observations),
        "fcf_margin": _fcf_margin_series(observations),
        "net_debt_to_ebitda": _net_debt_to_ebitda_series(observations),
    }
    for name in ("pe", "ev_ebitda", "price_fcf"):
        evidence[f"{name}_multiple"] = _multiple_series(valuation, name)
    return evidence


def _growth_series(observations: list[FundamentalObservation]) -> EvidenceSeries:
    ordered = sorted(
        [item for item in observations if item.value is not None and item.value > 0],
        key=lambda item: item.end_date,
    )
    result = EvidenceSeries(
        derivation="annualized consecutive SEC revenue growth",
        unit="ratio",
    )
    for first, second in zip(ordered, ordered[1:]):
        elapsed = (second.end_date - first.end_date).days / 365.25
        if elapsed <= 0:
            continue
        result.values.append((second.value / first.value) ** (1 / elapsed) - 1)
        result.dates.append(second.end_date)
        result.accessions.extend([first.accession, second.accession])
        result.urls.extend([first.source_url, second.source_url])
    return result


def _ratio_series(
    observations: dict[str, list[FundamentalObservation]],
    numerator: str,
    denominator: str,
    derivation: str,
) -> EvidenceSeries:
    left = _by_period(observations.get(numerator, []))
    right = _by_period(observations.get(denominator, []))
    result = EvidenceSeries(derivation=derivation, unit="ratio")
    for period in sorted(set(left) & set(right)):
        numerator_fact, denominator_fact = left[period], right[period]
        if denominator_fact.value is None or denominator_fact.value <= 0:
            continue
        result.values.append(float(numerator_fact.value) / float(denominator_fact.value))
        result.dates.append(period)
        result.accessions.extend([numerator_fact.accession, denominator_fact.accession])
        result.urls.extend([numerator_fact.source_url, denominator_fact.source_url])
    return result


def _ebitda_margin_series(
    observations: dict[str, list[FundamentalObservation]],
) -> EvidenceSeries:
    operating = _by_period(observations.get("operating_income", []))
    depreciation = _by_period(observations.get("depreciation_amortization", []))
    revenue = _by_period(observations.get("revenue", []))
    result = EvidenceSeries(
        derivation="(operating income + depreciation/amortization) / revenue",
        unit="ratio",
    )
    for period in sorted(set(operating) & set(depreciation) & set(revenue)):
        facts = (operating[period], depreciation[period], revenue[period])
        if facts[2].value is None or facts[2].value <= 0:
            continue
        value = (float(facts[0].value) + float(facts[1].value)) / float(facts[2].value)
        _append_evidence(result, period, value, facts)
    return result


def _fcf_margin_series(
    observations: dict[str, list[FundamentalObservation]],
) -> EvidenceSeries:
    ocf = _by_period(observations.get("operating_cash_flow", []))
    capex = _by_period(observations.get("capex", []))
    revenue = _by_period(observations.get("revenue", []))
    result = EvidenceSeries(
        derivation="(operating cash flow - capex) / revenue",
        unit="ratio",
    )
    for period in sorted(set(ocf) & set(capex) & set(revenue)):
        facts = (ocf[period], capex[period], revenue[period])
        if facts[2].value is None or facts[2].value <= 0:
            continue
        value = (float(facts[0].value) - float(facts[1].value)) / float(facts[2].value)
        _append_evidence(result, period, value, facts)
    return result


def _net_debt_to_ebitda_series(
    observations: dict[str, list[FundamentalObservation]],
) -> EvidenceSeries:
    cash = _by_period(observations.get("cash", []))
    operating = _by_period(observations.get("operating_income", []))
    depreciation = _by_period(observations.get("depreciation_amortization", []))
    debts = _debt_by_period(observations)
    result = EvidenceSeries(
        derivation="(reported debt - cash) / (operating income + D&A)",
        unit="x",
    )
    for period in sorted(set(cash) & set(operating) & set(depreciation) & set(debts)):
        debt_value, debt_facts = debts[period]
        ebitda = float(operating[period].value) + float(depreciation[period].value)
        if ebitda <= 0:
            continue
        facts = (*debt_facts, cash[period], operating[period], depreciation[period])
        _append_evidence(
            result, period, (debt_value - float(cash[period].value)) / ebitda, facts
        )
    return result


def _multiple_series(
    valuation: ValuationAnalysisResult | None, name: str
) -> EvidenceSeries:
    result = EvidenceSeries(
        derivation=f"historical point-in-time {name} multiple",
        unit="x",
    )
    multiple = valuation.multiples.get(name) if valuation is not None else None
    if multiple is None:
        return result
    for point in multiple.history:
        if point.value <= 0:
            continue
        result.values.append(point.value)
        result.dates.append(point.price_date)
        result.accessions.extend(point.source_accessions)
    return result


def _series_assumption(
    name: str,
    series: EvidenceSeries,
    statistic: str,
    minimum_points: int,
    *,
    adverse_high: bool = False,
) -> ScenarioAssumption:
    if len(series.values) < minimum_points:
        return ScenarioAssumption(
            name=name,
            status=DataStatus.DATA_UNAVAILABLE,
            unit=series.unit,
            derivation=f"{statistic} of {series.derivation}",
            observation_count=len(series.values),
            period_start=min(series.dates) if series.dates else None,
            period_end=max(series.dates) if series.dates else None,
            source_accessions=list(dict.fromkeys(series.accessions)),
            source_urls=list(dict.fromkeys(series.urls)),
            reason=f"{len(series.values)} observations; {minimum_points} required",
        )
    if statistic == "median":
        selected = median(series.values)
    elif statistic == "lower_quartile":
        selected = _quantile(series.values, 0.75 if adverse_high else 0.25)
    else:
        selected = _quantile(series.values, 0.25 if adverse_high else 0.75)
    return ScenarioAssumption(
        name=name,
        value=selected,
        status=DataStatus.AVAILABLE,
        unit=series.unit,
        derivation=f"{statistic} of {series.derivation}",
        observation_count=len(series.values),
        period_start=min(series.dates) if series.dates else None,
        period_end=max(series.dates) if series.dates else None,
        source_accessions=list(dict.fromkeys(series.accessions)),
        source_urls=list(dict.fromkeys(series.urls)),
    )


def _latest_metric_assumption(
    fundamental: FundamentalAnalysisResult, name: str
) -> ScenarioAssumption:
    lookup = {
        "revenue": ("revenue", "USD"),
        "diluted_shares": ("diluted_shares", "shares"),
        "debt": ("debt", "USD"),
        "cash": ("cash", "USD"),
    }
    metric_name, unit = lookup[name]
    metric = fundamental.metrics.get(metric_name)
    if name == "diluted_shares" and (metric is None or metric.value is None):
        metric = fundamental.metrics.get("shares_outstanding")
        metric_name = "shares_outstanding"
    if metric is None or metric.value is None:
        return ScenarioAssumption(
            name=name,
            status=DataStatus.DATA_UNAVAILABLE,
            unit=unit,
            derivation=f"latest point-in-time SEC {metric_name}",
            reason=f"{metric_name} is unavailable",
        )
    return ScenarioAssumption(
        name=name,
        value=metric.value,
        status=DataStatus.AVAILABLE,
        unit=unit,
        derivation=f"latest point-in-time SEC {metric_name}",
        observation_count=1,
        period_start=metric.period_start,
        period_end=metric.period_end,
        source_accessions=metric.source_accessions,
    )


def _dcf_assumption(
    valuation: ValuationAnalysisResult | None,
    scenario: str,
    name: str,
    as_of: datetime,
) -> ScenarioAssumption:
    item = valuation.dcf_scenarios.get(scenario) if valuation is not None else None
    value = item.assumptions.get(name) if item is not None else None
    if (
        item is None
        or item.assumption_date is None
        or item.assumption_date > as_of.date()
        or not isinstance(value, (int, float))
    ):
        return ScenarioAssumption(
            name=name,
            status=DataStatus.DATA_UNAVAILABLE,
            unit="ratio",
            derivation=f"dated, sourced {scenario} DCF assumption",
            reason=f"sourced {scenario} DCF {name} is unavailable",
        )
    return ScenarioAssumption(
        name=name,
        value=float(value),
        status=DataStatus.AVAILABLE,
        unit="ratio",
        derivation=(
            f"dated {scenario} DCF assumption from {item.assumption_source}"
        ),
        observation_count=1,
        period_start=item.assumption_date,
        period_end=item.assumption_date,
    )


def _assumption_coverage(assumptions: dict[str, ScenarioAssumption]) -> float:
    observed = {
        "revenue_growth": _available(assumptions, "revenue_growth"),
        "margin": _available(assumptions, "operating_margin")
        and _available(assumptions, "net_margin"),
        "eps": _available(assumptions, "net_margin")
        and _available(assumptions, "diluted_shares"),
        "free_cash_flow": _available(assumptions, "fcf_margin")
        and _available(assumptions, "diluted_shares"),
        "multiple": any(
            _available(assumptions, name)
            for name in ("pe_multiple", "ev_ebitda_multiple", "price_fcf_multiple")
        ),
        "wacc": _available(assumptions, "wacc"),
        "terminal_growth": _available(assumptions, "terminal_growth"),
    }
    return round(
        sum(observed.values()) / len(CORE_COVERAGE_DIMENSIONS), 4
    )


def _compound_revenue(
    months: int, assumptions: dict[str, ScenarioAssumption]
) -> MetricValue:
    revenue = _value(assumptions.get("revenue"))
    growth = _value(assumptions.get("revenue_growth"))
    if revenue is None or revenue <= 0 or growth is None or growth <= -1:
        return MetricValue.unavailable("positive revenue and valid growth are required")
    return MetricValue.available(revenue * (1 + growth) ** (months / 12))


def _project_per_share(
    revenue: MetricValue,
    margin: ScenarioAssumption | None,
    shares: ScenarioAssumption | None,
    *,
    label: str,
) -> MetricValue:
    margin_value, shares_value = _value(margin), _value(shares)
    if revenue.value is None or margin_value is None or shares_value is None or shares_value <= 0:
        return MetricValue.unavailable(
            f"revenue, margin, and positive shares are required for {label}"
        )
    return MetricValue.available(revenue.value * margin_value / shares_value)


def _project_amount(
    revenue: MetricValue,
    margin: ScenarioAssumption | None,
    *,
    label: str,
) -> MetricValue:
    margin_value = _value(margin)
    if revenue.value is None or margin_value is None:
        return MetricValue.unavailable(f"revenue and margin are required for {label}")
    return MetricValue.available(revenue.value * margin_value)


def _pe_value(eps: MetricValue, multiple: ScenarioAssumption | None) -> MetricValue:
    value = _value(multiple)
    if eps.value is None or eps.value <= 0 or value is None or value <= 0:
        return MetricValue.unavailable("positive EPS and P/E multiple are required")
    return MetricValue.available(eps.value * value)


def _price_fcf_value(
    fcf: MetricValue,
    shares: ScenarioAssumption | None,
    multiple: ScenarioAssumption | None,
) -> MetricValue:
    shares_value, multiple_value = _value(shares), _value(multiple)
    if (
        fcf.value is None
        or fcf.value <= 0
        or shares_value is None
        or shares_value <= 0
        or multiple_value is None
        or multiple_value <= 0
    ):
        return MetricValue.unavailable(
            "positive FCF, shares, and P/FCF multiple are required"
        )
    return MetricValue.available(fcf.value / shares_value * multiple_value)


def _ev_ebitda_value(
    revenue: MetricValue, assumptions: dict[str, ScenarioAssumption]
) -> MetricValue:
    margin = _value(assumptions.get("ebitda_margin"))
    multiple = _value(assumptions.get("ev_ebitda_multiple"))
    debt = _value(assumptions.get("debt"))
    cash = _value(assumptions.get("cash"))
    shares = _value(assumptions.get("diluted_shares"))
    if (
        revenue.value is None
        or margin is None
        or margin <= 0
        or multiple is None
        or multiple <= 0
        or debt is None
        or cash is None
        or shares is None
        or shares <= 0
    ):
        return MetricValue.unavailable(
            "revenue, positive EBITDA margin/multiple/shares, debt, and cash are required"
        )
    equity_value = revenue.value * margin * multiple - debt + cash
    if equity_value <= 0:
        return MetricValue.unavailable("EV/EBITDA assumptions produce non-positive equity value")
    return MetricValue.available(equity_value / shares)


def _invalidation_levels(
    bear: ScenarioCaseResult | None,
) -> tuple[list[FundamentalInvalidationLevel], list[str]]:
    if bear is None:
        return [], [
            "revenue_growth", "operating_margin", "free_cash_flow_margin",
            "net_debt_to_ebitda", "revenue_guidance", "order_book", "market_share",
        ]
    definitions = (
        ("revenue_growth", "<", "ratio", "growth below the observed lower-quartile regime"),
        ("operating_margin", "<", "ratio", "margin below the observed lower-quartile regime"),
        ("fcf_margin", "<", "ratio", "FCF margin below the observed lower-quartile regime"),
        ("net_debt_to_ebitda", ">", "x", "leverage above the observed upper-quartile regime"),
    )
    levels: list[FundamentalInvalidationLevel] = []
    missing: list[str] = []
    for name, operator, unit, rationale in definitions:
        assumption = bear.assumptions.get(name)
        if assumption is None or assumption.value is None:
            missing.append(name)
            continue
        levels.append(
            FundamentalInvalidationLevel(
                metric=name,
                operator=operator,
                threshold=assumption.value,
                unit=unit,
                rationale=rationale,
                observation_count=assumption.observation_count,
                source_accessions=assumption.source_accessions,
            )
        )
    missing.extend(["revenue_guidance", "order_book", "market_share"])
    return levels, missing


def _unavailable_result(
    security: Security,
    valuation: ValuationAnalysisResult | None,
    current_price: float | None,
    as_of: datetime,
    retrieved_at: datetime,
    target_horizon_months: int,
    reason: str,
) -> ScenarioAnalysisResult:
    targets = build_target_summary(
        {}, valuation, target_horizon_months=target_horizon_months
    )
    return ScenarioAnalysisResult(
        ticker=security.ticker,
        company=security.company,
        as_of=as_of,
        status=DataStatus.DATA_UNAVAILABLE,
        data_quality=DataQuality.UNAVAILABLE,
        targets=targets,
        risk_reward=calculate_risk_reward(current_price, targets),
        missing_invalidation_dimensions=[
            "revenue_growth", "operating_margin", "free_cash_flow_margin",
            "net_debt_to_ebitda", "revenue_guidance", "order_book", "market_share",
        ],
        sources=[],
        retrieved_at=retrieved_at,
        error=reason,
    )


def _scenario_sources(
    fundamental: FundamentalAnalysisResult,
    valuation: ValuationAnalysisResult | None,
) -> list[dict[str, object]]:
    sources = [{**source, "role": "scenario_fundamentals"} for source in fundamental.sources]
    if valuation is not None:
        sources.extend(
            {**source, "role": "scenario_valuation"} for source in valuation.sources
        )
    return sources


def _by_period(
    observations: list[FundamentalObservation],
) -> dict[date, FundamentalObservation]:
    return {
        item.end_date: item
        for item in observations
        if item.value is not None
    }


def _debt_by_period(
    observations: dict[str, list[FundamentalObservation]],
) -> dict[date, tuple[float, tuple[FundamentalObservation, ...]]]:
    direct = _by_period(observations.get("long_term_debt_total", []))
    current = _by_period(observations.get("current_debt", []))
    noncurrent = _by_period(observations.get("noncurrent_debt", []))
    short = _by_period(observations.get("short_term_borrowings", []))
    periods = set(direct) | (set(current) & set(noncurrent))
    result: dict[date, tuple[float, tuple[FundamentalObservation, ...]]] = {}
    for period in periods:
        if period in direct:
            facts = [direct[period]]
            value = float(direct[period].value)
        else:
            facts = [current[period], noncurrent[period]]
            value = float(current[period].value) + float(noncurrent[period].value)
        if period in short:
            facts.append(short[period])
            value += float(short[period].value)
        result[period] = (value, tuple(facts))
    return result


def _append_evidence(
    result: EvidenceSeries,
    period: date,
    value: float,
    facts: tuple[FundamentalObservation, ...],
) -> None:
    result.values.append(value)
    result.dates.append(period)
    result.accessions.extend(item.accession for item in facts)
    result.urls.extend(item.source_url for item in facts)


def _metric_from_assumption(
    assumption: ScenarioAssumption | None, reason: str
) -> MetricValue:
    value = _value(assumption)
    return MetricValue.available(value) if value is not None else MetricValue.unavailable(reason)


def _value(assumption: ScenarioAssumption | None) -> float | None:
    return assumption.value if assumption is not None else None


def _available(assumptions: dict[str, ScenarioAssumption], name: str) -> bool:
    item = assumptions.get(name)
    return item is not None and item.status == DataStatus.AVAILABLE and item.value is not None


def _quantile(values: list[float], probability: float) -> float:
    """Linear sample quantile with no extrapolation beyond observed values."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


__all__ = ["analyze_scenarios"]
