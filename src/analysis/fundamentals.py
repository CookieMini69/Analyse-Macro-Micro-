"""Fundamental ratios, growth, cash flow, balance sheet, and quality scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from src.data.fundamentals import FundamentalDataResult
from src.models import (
    CalculatedFundamentalMetric,
    DataQuality,
    DataStatus,
    FundamentalAnalysisResult,
    FundamentalObservation,
    FundamentalQualityScore,
    FundamentalScoreComponent,
)


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    end_date: date
    value: float
    accessions: tuple[str, ...]
    start_date: date | None = None


def analyze_fundamentals(
    data: FundamentalDataResult, *, minimum_score_coverage: float = 0.50
) -> FundamentalAnalysisResult:
    """Calculate annual metrics strictly from facts available at ``data.as_of``."""

    if data.status != DataStatus.AVAILABLE or not data.observations:
        score = FundamentalQualityScore(
            score=None,
            observed_score=None,
            coverage=0.0,
            status=data.status,
            components={},
            reason=data.error or "fundamental data unavailable",
        )
        return FundamentalAnalysisResult(
            ticker=data.security.ticker,
            cik=data.cik,
            company=data.company,
            as_of=data.as_of,
            status=data.status,
            data_quality=data.data_quality,
            annual_observations=data.observations,
            metrics={},
            quality_score=score,
            retrieved_at=data.retrieved_at,
            sources=data.sources,
            error=data.error,
        )

    raw_series = {
        name: [
            SeriesPoint(
                end_date=item.end_date,
                start_date=item.start_date,
                value=float(item.value),
                accessions=(item.accession,),
            )
            for item in observations
            if item.value is not None
        ]
        for name, observations in data.observations.items()
    }
    fcf_series = _combine_series(
        raw_series.get("operating_cash_flow", []),
        raw_series.get("capex", []),
        lambda operating_cash_flow, capex: operating_cash_flow - capex,
    )
    ebitda_series = _combine_series(
        raw_series.get("operating_income", []),
        raw_series.get("depreciation_amortization", []),
        lambda operating_income, depreciation: operating_income + depreciation,
    )
    debt_series = _debt_series(raw_series)

    latest_period_end = _latest_period_end(raw_series)
    metrics: dict[str, CalculatedFundamentalMetric] = {}
    direct_names = (
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps_diluted",
        "operating_cash_flow",
        "capex",
        "cash",
        "equity",
        "current_assets",
        "current_liabilities",
        "interest_expense",
        "pretax_income",
        "income_tax_expense",
        "diluted_shares",
        "shares_outstanding",
        "dividends_paid",
    )
    for name in direct_names:
        point = _point_at(raw_series.get(name, []), latest_period_end)
        metrics[name] = _reported_metric(name, point, _unit_for(name))

    fcf = _point_at(fcf_series, latest_period_end)
    ebitda = _point_at(ebitda_series, latest_period_end)
    debt = _point_at(debt_series, latest_period_end)
    metrics["free_cash_flow"] = _point_metric(
        "free_cash_flow",
        fcf,
        "USD",
        "operating_cash_flow - capex",
        ["operating_cash_flow", "capex"],
    )
    metrics["ebitda_calculated"] = _point_metric(
        "ebitda_calculated",
        ebitda,
        "USD",
        "operating_income + depreciation_amortization",
        ["operating_income", "depreciation_amortization"],
    )
    metrics["debt"] = _point_metric(
        "debt",
        debt,
        "USD",
        "reported long-term debt plus disclosed short-term borrowings when available",
        [
            "long_term_debt_total",
            "current_debt",
            "noncurrent_debt",
            "short_term_borrowings",
        ],
    )

    growth_series = {
        "revenue_cagr": raw_series.get("revenue", []),
        "eps_cagr": raw_series.get("eps_diluted", []),
        "ebitda_cagr": ebitda_series,
        "fcf_cagr": fcf_series,
    }
    for name, points in growth_series.items():
        metrics[name] = _cagr_metric(name, points)

    ratio_definitions = {
        "gross_margin": ("gross_profit", "revenue"),
        "operating_margin": ("operating_income", "revenue"),
        "net_margin": ("net_income", "revenue"),
        "operating_cash_flow_margin": ("operating_cash_flow", "revenue"),
    }
    for name, (numerator, denominator) in ratio_definitions.items():
        metrics[name] = _ratio_metric(
            name,
            _point_at(raw_series.get(numerator, []), latest_period_end),
            _point_at(raw_series.get(denominator, []), latest_period_end),
            numerator,
            denominator,
        )
    metrics["ebitda_margin"] = _ratio_metric(
        "ebitda_margin",
        ebitda,
        _point_at(raw_series.get("revenue", []), latest_period_end),
        "ebitda_calculated",
        "revenue",
    )
    metrics["fcf_margin"] = _ratio_metric(
        "fcf_margin",
        fcf,
        _point_at(raw_series.get("revenue", []), latest_period_end),
        "free_cash_flow",
        "revenue",
    )

    equity = _point_at(raw_series.get("equity", []), latest_period_end)
    prior_equity = _prior_point(raw_series.get("equity", []), latest_period_end)
    net_income = _point_at(raw_series.get("net_income", []), latest_period_end)
    metrics["roe"] = _average_balance_return_metric(
        "roe", net_income, equity, prior_equity, "net_income", "equity"
    )

    cash = _point_at(raw_series.get("cash", []), latest_period_end)
    metrics["debt_to_equity"] = _ratio_metric(
        "debt_to_equity", debt, equity, "debt", "equity", positive_denominator=True
    )
    metrics["cash_to_debt"] = _ratio_metric(
        "cash_to_debt", cash, debt, "cash", "debt", positive_denominator=True
    )
    metrics["current_ratio"] = _ratio_metric(
        "current_ratio",
        _point_at(raw_series.get("current_assets", []), latest_period_end),
        _point_at(raw_series.get("current_liabilities", []), latest_period_end),
        "current_assets",
        "current_liabilities",
        positive_denominator=True,
    )

    net_debt = _subtract_metric("net_debt", debt, cash, "debt", "cash", "USD")
    metrics["net_debt"] = net_debt
    metrics["net_debt_to_ebitda"] = _calculated_ratio_metric(
        "net_debt_to_ebitda", net_debt, ebitda, "net_debt", "ebitda_calculated"
    )
    metrics["interest_coverage"] = _ratio_metric(
        "interest_coverage",
        _point_at(raw_series.get("operating_income", []), latest_period_end),
        _absolute_point(_point_at(raw_series.get("interest_expense", []), latest_period_end)),
        "operating_income",
        "abs(interest_expense)",
        positive_denominator=True,
    )

    pretax = _point_at(raw_series.get("pretax_income", []), latest_period_end)
    tax = _point_at(raw_series.get("income_tax_expense", []), latest_period_end)
    effective_tax_rate = _ratio_metric(
        "effective_tax_rate",
        tax,
        pretax,
        "income_tax_expense",
        "pretax_income",
        positive_denominator=True,
    )
    if effective_tax_rate.value is not None and not 0 <= effective_tax_rate.value <= 1:
        effective_tax_rate = _unavailable_metric(
            "effective_tax_rate", "reported effective tax rate falls outside [0, 1]"
        )
    metrics["effective_tax_rate"] = effective_tax_rate
    metrics["roic"] = _roic_metric(
        _point_at(raw_series.get("operating_income", []), latest_period_end),
        effective_tax_rate,
        debt,
        equity,
        cash,
    )

    diluted_shares = _point_at(raw_series.get("diluted_shares", []), latest_period_end)
    metrics["fcf_per_share"] = _ratio_metric(
        "fcf_per_share",
        fcf,
        diluted_shares,
        "free_cash_flow",
        "diluted_shares",
        unit="USD/shares",
        positive_denominator=True,
    )
    operating_cash_flow = _point_at(
        raw_series.get("operating_cash_flow", []), latest_period_end
    )
    metrics["cash_conversion"] = _ratio_metric(
        "cash_conversion",
        operating_cash_flow,
        net_income,
        "operating_cash_flow",
        "net_income",
        positive_denominator=True,
    )
    metrics["positive_fcf_year_ratio"] = _positive_year_ratio(fcf_series)

    score = score_fundamental_quality(
        metrics, minimum_coverage=minimum_score_coverage
    )
    quality = data.data_quality
    if score.coverage < 0.75 and quality == DataQuality.MEDIUM:
        quality = DataQuality.LOW
    return FundamentalAnalysisResult(
        ticker=data.security.ticker,
        cik=data.cik,
        company=data.company,
        as_of=data.as_of,
        status=DataStatus.AVAILABLE,
        data_quality=quality,
        annual_observations=data.observations,
        metrics=metrics,
        quality_score=score,
        latest_period_end=latest_period_end,
        retrieved_at=data.retrieved_at,
        sources=data.sources,
        error=data.error,
    )


SCORE_RULES: dict[str, tuple[tuple[float, float], ...]] = {
    "revenue_cagr": ((-0.10, 0), (0, 30), (0.05, 60), (0.10, 80), (0.20, 100)),
    "eps_cagr": ((-0.15, 0), (0, 30), (0.08, 65), (0.15, 85), (0.25, 100)),
    "ebitda_cagr": ((-0.10, 0), (0, 30), (0.06, 60), (0.12, 85), (0.22, 100)),
    "fcf_cagr": ((-0.15, 0), (0, 30), (0.08, 60), (0.15, 85), (0.25, 100)),
    "gross_margin": ((0, 0), (0.20, 40), (0.40, 75), (0.60, 100)),
    "operating_margin": ((-0.05, 0), (0.05, 35), (0.15, 70), (0.30, 100)),
    "net_margin": ((-0.05, 0), (0.03, 35), (0.10, 70), (0.20, 100)),
    "roe": ((-0.10, 0), (0.05, 40), (0.15, 75), (0.30, 100)),
    "roic": ((-0.05, 0), (0.05, 40), (0.12, 75), (0.20, 100)),
    "debt_to_equity": ((0, 100), (0.5, 85), (1, 65), (2, 35), (4, 0)),
    "net_debt_to_ebitda": ((-1, 100), (0, 90), (1, 75), (2, 60), (3, 40), (5, 0)),
    "interest_coverage": ((0, 0), (1, 20), (3, 55), (6, 80), (12, 100)),
    "cash_to_debt": ((0, 0), (0.25, 35), (0.5, 60), (1, 85), (2, 100)),
    "current_ratio": ((0.5, 0), (1, 40), (1.5, 75), (2, 100), (4, 80)),
    "fcf_margin": ((-0.10, 0), (0, 30), (0.05, 55), (0.10, 75), (0.20, 100)),
    "operating_cash_flow_margin": ((-0.05, 0), (0, 25), (0.08, 60), (0.15, 85), (0.25, 100)),
    "cash_conversion": ((0, 0), (0.5, 40), (1, 80), (1.5, 100), (3, 70)),
    "positive_fcf_year_ratio": ((0, 0), (0.5, 50), (0.75, 75), (1, 100)),
}

COMPONENT_METRICS = {
    "growth": ("revenue_cagr", "eps_cagr", "ebitda_cagr", "fcf_cagr"),
    "profitability": ("gross_margin", "operating_margin", "net_margin", "roe", "roic"),
    "balance_sheet": (
        "debt_to_equity",
        "net_debt_to_ebitda",
        "interest_coverage",
        "cash_to_debt",
        "current_ratio",
    ),
    "cash_flow": (
        "fcf_margin",
        "operating_cash_flow_margin",
        "cash_conversion",
        "positive_fcf_year_ratio",
    ),
}

COMPONENT_WEIGHTS = {
    "growth": 0.25,
    "profitability": 0.30,
    "balance_sheet": 0.25,
    "cash_flow": 0.20,
}


def score_fundamental_quality(
    metrics: dict[str, CalculatedFundamentalMetric], *, minimum_coverage: float = 0.50
) -> FundamentalQualityScore:
    """Apply explicit bands; unavailable inputs are not imputed."""

    components: dict[str, FundamentalScoreComponent] = {}
    for component_name, metric_names in COMPONENT_METRICS.items():
        metric_scores: dict[str, float | None] = {}
        for metric_name in metric_names:
            metric = metrics.get(metric_name)
            metric_scores[metric_name] = (
                _piecewise_score(metric.value, SCORE_RULES[metric_name])
                if metric is not None and metric.value is not None
                else None
            )
        available = [value for value in metric_scores.values() if value is not None]
        coverage = len(available) / len(metric_names)
        observed = sum(available) / len(available) if available else None
        adjusted = observed * coverage if observed is not None else None
        components[component_name] = FundamentalScoreComponent(
            name=component_name,
            observed_score=round(observed, 2) if observed is not None else None,
            adjusted_score=round(adjusted, 2) if adjusted is not None else None,
            coverage=round(coverage, 4),
            metric_scores={
                key: round(value, 2) if value is not None else None
                for key, value in metric_scores.items()
            },
        )

    coverage = sum(
        COMPONENT_WEIGHTS[name] * component.coverage
        for name, component in components.items()
    )
    available_weight = sum(
        COMPONENT_WEIGHTS[name]
        for name, component in components.items()
        if component.observed_score is not None
    )
    observed_score = (
        sum(
            COMPONENT_WEIGHTS[name] * component.observed_score
            for name, component in components.items()
            if component.observed_score is not None
        )
        / available_weight
        if available_weight
        else None
    )
    adjusted_score = sum(
        COMPONENT_WEIGHTS[name] * (component.adjusted_score or 0.0)
        for name, component in components.items()
    )
    status = (
        DataStatus.AVAILABLE
        if observed_score is not None and coverage >= minimum_coverage
        else DataStatus.DATA_UNAVAILABLE
    )
    return FundamentalQualityScore(
        score=round(adjusted_score, 2) if status == DataStatus.AVAILABLE else None,
        observed_score=round(observed_score, 2) if observed_score is not None else None,
        coverage=round(coverage, 4),
        status=status,
        components=components,
        reason=(
            None
            if status == DataStatus.AVAILABLE
            else f"score coverage {coverage:.2%} is below required {minimum_coverage:.2%}"
        ),
    )


def _latest_period_end(series: dict[str, list[SeriesPoint]]) -> date | None:
    revenue = series.get("revenue", [])
    if revenue:
        return revenue[-1].end_date
    ends = [point.end_date for points in series.values() for point in points]
    return max(ends) if ends else None


def _point_at(points: list[SeriesPoint], end_date: date | None) -> SeriesPoint | None:
    return next((point for point in reversed(points) if point.end_date == end_date), None)


def _prior_point(points: list[SeriesPoint], end_date: date | None) -> SeriesPoint | None:
    eligible = [point for point in points if end_date is not None and point.end_date < end_date]
    return eligible[-1] if eligible else None


def _combine_series(
    left: list[SeriesPoint],
    right: list[SeriesPoint],
    operation: Callable[[float, float], float],
) -> list[SeriesPoint]:
    right_by_end = {point.end_date: point for point in right}
    result = []
    for left_point in left:
        right_point = right_by_end.get(left_point.end_date)
        if right_point is None:
            continue
        result.append(
            SeriesPoint(
                end_date=left_point.end_date,
                start_date=left_point.start_date,
                value=operation(left_point.value, right_point.value),
                accessions=tuple(
                    dict.fromkeys(left_point.accessions + right_point.accessions)
                ),
            )
        )
    return result


def _debt_series(series: dict[str, list[SeriesPoint]]) -> list[SeriesPoint]:
    direct = {point.end_date: point for point in series.get("long_term_debt_total", [])}
    current = {point.end_date: point for point in series.get("current_debt", [])}
    noncurrent = {point.end_date: point for point in series.get("noncurrent_debt", [])}
    short_term = {point.end_date: point for point in series.get("short_term_borrowings", [])}
    ends = sorted(set(direct) | (set(current) & set(noncurrent)))
    result = []
    for end in ends:
        if end in direct:
            base = direct[end]
            value = base.value
            accessions = base.accessions
        else:
            value = current[end].value + noncurrent[end].value
            accessions = current[end].accessions + noncurrent[end].accessions
        if end in short_term:
            value += short_term[end].value
            accessions += short_term[end].accessions
        result.append(
            SeriesPoint(end, value, tuple(dict.fromkeys(accessions)))
        )
    return result


def _reported_metric(
    name: str, point: SeriesPoint | None, unit: str | None
) -> CalculatedFundamentalMetric:
    return _point_metric(name, point, unit, "reported SEC XBRL fact", [name])


def _point_metric(
    name: str,
    point: SeriesPoint | None,
    unit: str | None,
    formula: str,
    inputs: list[str],
) -> CalculatedFundamentalMetric:
    if point is None:
        return _unavailable_metric(name, "required aligned annual fact unavailable", inputs)
    return CalculatedFundamentalMetric(
        name=name,
        value=point.value,
        unit=unit,
        status=DataStatus.AVAILABLE,
        formula=formula,
        inputs=inputs,
        period_start=point.start_date,
        period_end=point.end_date,
        source_accessions=list(point.accessions),
    )


def _cagr_metric(name: str, points: list[SeriesPoint]) -> CalculatedFundamentalMetric:
    if len(points) < 2:
        return _unavailable_metric(name, "at least two annual observations are required")
    first, last = points[0], points[-1]
    years = (last.end_date - first.end_date).days / 365.2425
    if years <= 0 or first.value <= 0 or last.value <= 0:
        return _unavailable_metric(
            name, "CAGR requires positive endpoints and a positive time span"
        )
    value = (last.value / first.value) ** (1 / years) - 1
    return CalculatedFundamentalMetric(
        name=name,
        value=value,
        unit="ratio",
        status=DataStatus.AVAILABLE,
        formula="(latest / earliest) ** (1 / elapsed_years) - 1",
        inputs=[name.removesuffix("_cagr")],
        period_start=first.end_date,
        period_end=last.end_date,
        source_accessions=list(
            dict.fromkeys(first.accessions + last.accessions)
        ),
    )


def _ratio_metric(
    name: str,
    numerator: SeriesPoint | None,
    denominator: SeriesPoint | None,
    numerator_name: str,
    denominator_name: str,
    *,
    unit: str = "ratio",
    positive_denominator: bool = False,
) -> CalculatedFundamentalMetric:
    if numerator is None or denominator is None:
        return _unavailable_metric(
            name, "required aligned annual inputs unavailable", [numerator_name, denominator_name]
        )
    if denominator.value == 0 or (positive_denominator and denominator.value <= 0):
        return _unavailable_metric(
            name, "denominator is zero or non-positive", [numerator_name, denominator_name]
        )
    return CalculatedFundamentalMetric(
        name=name,
        value=numerator.value / denominator.value,
        unit=unit,
        status=DataStatus.AVAILABLE,
        formula=f"{numerator_name} / {denominator_name}",
        inputs=[numerator_name, denominator_name],
        period_end=numerator.end_date,
        source_accessions=list(
            dict.fromkeys(numerator.accessions + denominator.accessions)
        ),
    )


def _calculated_ratio_metric(
    name: str,
    numerator: CalculatedFundamentalMetric,
    denominator: SeriesPoint | None,
    numerator_name: str,
    denominator_name: str,
) -> CalculatedFundamentalMetric:
    if numerator.value is None or denominator is None or denominator.value <= 0:
        return _unavailable_metric(
            name, "required inputs unavailable or denominator non-positive", [numerator_name, denominator_name]
        )
    return CalculatedFundamentalMetric(
        name=name,
        value=numerator.value / denominator.value,
        unit="ratio",
        status=DataStatus.AVAILABLE,
        formula=f"{numerator_name} / {denominator_name}",
        inputs=[numerator_name, denominator_name],
        period_end=denominator.end_date,
        source_accessions=list(
            dict.fromkeys(numerator.source_accessions + list(denominator.accessions))
        ),
    )


def _subtract_metric(
    name: str,
    left: SeriesPoint | None,
    right: SeriesPoint | None,
    left_name: str,
    right_name: str,
    unit: str,
) -> CalculatedFundamentalMetric:
    if left is None or right is None:
        return _unavailable_metric(name, "required aligned annual inputs unavailable", [left_name, right_name])
    return CalculatedFundamentalMetric(
        name=name,
        value=left.value - right.value,
        unit=unit,
        status=DataStatus.AVAILABLE,
        formula=f"{left_name} - {right_name}",
        inputs=[left_name, right_name],
        period_end=left.end_date,
        source_accessions=list(dict.fromkeys(left.accessions + right.accessions)),
    )


def _average_balance_return_metric(
    name: str,
    numerator: SeriesPoint | None,
    current_balance: SeriesPoint | None,
    prior_balance: SeriesPoint | None,
    numerator_name: str,
    balance_name: str,
) -> CalculatedFundamentalMetric:
    if numerator is None or current_balance is None or prior_balance is None:
        return _unavailable_metric(name, "current and prior aligned balance values are required")
    average = (current_balance.value + prior_balance.value) / 2
    if average <= 0:
        return _unavailable_metric(name, "average balance is non-positive")
    return CalculatedFundamentalMetric(
        name=name,
        value=numerator.value / average,
        unit="ratio",
        status=DataStatus.AVAILABLE,
        formula=f"{numerator_name} / average(current {balance_name}, prior {balance_name})",
        inputs=[numerator_name, balance_name],
        period_end=numerator.end_date,
        source_accessions=list(
            dict.fromkeys(
                numerator.accessions + current_balance.accessions + prior_balance.accessions
            )
        ),
    )


def _roic_metric(
    operating_income: SeriesPoint | None,
    tax_rate: CalculatedFundamentalMetric,
    debt: SeriesPoint | None,
    equity: SeriesPoint | None,
    cash: SeriesPoint | None,
) -> CalculatedFundamentalMetric:
    if (
        operating_income is None
        or tax_rate.value is None
        or debt is None
        or equity is None
        or cash is None
    ):
        return _unavailable_metric("roic", "NOPAT or invested-capital inputs unavailable")
    invested_capital = debt.value + equity.value - cash.value
    if invested_capital <= 0:
        return _unavailable_metric("roic", "invested capital is non-positive")
    nopat = operating_income.value * (1 - tax_rate.value)
    return CalculatedFundamentalMetric(
        name="roic",
        value=nopat / invested_capital,
        unit="ratio",
        status=DataStatus.AVAILABLE,
        formula="operating_income * (1 - effective_tax_rate) / (debt + equity - cash)",
        inputs=["operating_income", "effective_tax_rate", "debt", "equity", "cash"],
        period_end=operating_income.end_date,
        source_accessions=list(
            dict.fromkeys(
                operating_income.accessions
                + debt.accessions
                + equity.accessions
                + cash.accessions
                + tuple(tax_rate.source_accessions)
            )
        ),
    )


def _positive_year_ratio(points: list[SeriesPoint]) -> CalculatedFundamentalMetric:
    if not points:
        return _unavailable_metric("positive_fcf_year_ratio", "free cash flow history unavailable")
    return CalculatedFundamentalMetric(
        name="positive_fcf_year_ratio",
        value=sum(point.value > 0 for point in points) / len(points),
        unit="ratio",
        status=DataStatus.AVAILABLE,
        formula="positive annual FCF observations / available annual FCF observations",
        inputs=["free_cash_flow"],
        period_start=points[0].end_date,
        period_end=points[-1].end_date,
        source_accessions=list(
            dict.fromkeys(accession for point in points for accession in point.accessions)
        ),
    )


def _absolute_point(point: SeriesPoint | None) -> SeriesPoint | None:
    if point is None:
        return None
    return SeriesPoint(point.end_date, abs(point.value), point.accessions, point.start_date)


def _piecewise_score(value: float, knots: tuple[tuple[float, float], ...]) -> float:
    if value <= knots[0][0]:
        return float(knots[0][1])
    if value >= knots[-1][0]:
        return float(knots[-1][1])
    for (left_x, left_y), (right_x, right_y) in zip(knots, knots[1:]):
        if left_x <= value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return float(left_y + fraction * (right_y - left_y))
    raise ValueError("score knots must be ordered by input value")


def _unavailable_metric(
    name: str, reason: str, inputs: list[str] | None = None
) -> CalculatedFundamentalMetric:
    return CalculatedFundamentalMetric(
        name=name,
        value=None,
        status=DataStatus.DATA_UNAVAILABLE,
        reason=reason,
        inputs=inputs or [],
    )


def _unit_for(name: str) -> str | None:
    if name in {"eps_diluted"}:
        return "USD/shares"
    if name in {"diluted_shares", "shares_outstanding"}:
        return "shares"
    return "USD"
