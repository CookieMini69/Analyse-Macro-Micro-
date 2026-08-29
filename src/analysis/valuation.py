"""Point-in-time multiples, sector references, DCF, and valuation scoring."""

from __future__ import annotations

from datetime import UTC, date, datetime
from statistics import median
from typing import Iterable

import pandas as pd

from src.config import ValuationSettings
from src.data.sources import PriceHistoryResult
from src.forecasting.fair_value import calculate_dcf, calculate_reverse_dcf
from src.models import (
    DataQuality,
    DataStatus,
    DcfScenarioResult,
    FundamentalAnalysisResult,
    FundamentalObservation,
    HistoricalMultiplePoint,
    MetricValue,
    ReverseDcfResult,
    Security,
    ValuationAnalysisResult,
    ValuationMultiple,
    ValuationScore,
    ValuationScoreComponent,
)
from src.valuation_config import SecurityValuationConfig, ValuationConfig

MULTIPLE_FORMULAS = {
    "pe": "price / diluted EPS",
    "ev_ebitda": "(market capitalization + debt - cash) / EBITDA",
    "price_fcf": "market capitalization / free cash flow",
}
SCORE_WEIGHTS = {"pe": 0.20, "ev_ebitda": 0.20, "price_fcf": 0.20, "dcf": 0.40}
DISCOUNT_SCORE_BANDS = (
    (-0.50, 0.0),
    (-0.25, 20.0),
    (0.0, 50.0),
    (0.25, 70.0),
    (0.50, 85.0),
    (1.00, 100.0),
)
MAX_POST_FILING_PRICE_DELAY_DAYS = 7


def analyze_valuations(
    securities: list[Security],
    fundamentals: dict[str, FundamentalAnalysisResult],
    prices: dict[str, PriceHistoryResult],
    config: ValuationConfig,
    settings: ValuationSettings,
) -> dict[str, ValuationAnalysisResult]:
    """Calculate issuer valuations, then peer medians without self-inclusion."""

    preliminary: dict[str, ValuationAnalysisResult] = {}
    for security in securities:
        ticker = security.ticker.upper()
        fundamental = fundamentals.get(ticker)
        price = prices.get(ticker)
        if fundamental is None:
            continue
        preliminary[ticker] = analyze_valuation(
            security,
            fundamental,
            price,
            config.for_ticker(ticker),
            settings,
        )
    return _attach_sector_medians(preliminary, settings)


def analyze_valuation(
    security: Security,
    fundamental: FundamentalAnalysisResult,
    prices: PriceHistoryResult | None,
    dcf_config: SecurityValuationConfig | None,
    settings: ValuationSettings,
) -> ValuationAnalysisResult:
    """Calculate a single issuer strictly with information available at ``as_of``."""

    retrieved_at = datetime.now(UTC)
    price_row = _latest_price_on_or_before(
        prices.frame if prices is not None else pd.DataFrame(), fundamental.as_of.date()
    )
    valuation_price = _row_price(price_row)
    valuation_price_date = _row_date(price_row)
    currency = _row_text(price_row, "currency") or security.currency
    market_cap, market_cap_basis = _current_market_cap(
        security,
        fundamental,
        valuation_price,
        valuation_price_date,
        fundamental.as_of.date(),
    )
    fundamental_currencies = {
        observation.currency.upper()
        for observations in fundamental.annual_observations.values()
        for observation in observations
        if observation.currency
        and observation.unit != "shares"
    }
    if valuation_price is not None and not currency:
        currency_error = "price currency is unavailable; financial facts cannot be aligned"
    elif len(fundamental_currencies) > 1:
        currency_error = (
            "fundamental facts contain multiple currencies: "
            + ", ".join(sorted(fundamental_currencies))
        )
    elif (
        currency
        and fundamental_currencies
        and currency.upper() not in fundamental_currencies
    ):
        fact_currency = next(iter(fundamental_currencies))
        currency_error = (
            f"price currency {currency!r} is not aligned with "
            f"fundamental fact currency {fact_currency!r}"
        )
    else:
        currency_error = None
    multiples = _build_multiples(
        fundamental,
        prices.frame if prices is not None else pd.DataFrame(),
        valuation_price,
        market_cap,
        market_cap_basis,
        settings.historical_minimum_points,
        currency_error,
    )
    scenarios, reverse = _build_dcf(
        fundamental,
        dcf_config,
        valuation_price,
        settings,
        currency_error,
    )
    provisional = ValuationAnalysisResult(
        ticker=security.ticker,
        company=security.company,
        sector=security.sector,
        as_of=fundamental.as_of,
        valuation_price=valuation_price,
        valuation_price_date=valuation_price_date,
        valuation_currency=currency,
        market_cap=market_cap,
        market_cap_basis=market_cap_basis,
        status=DataStatus.DATA_UNAVAILABLE,
        data_quality=DataQuality.UNAVAILABLE,
        multiples=multiples,
        dcf_scenarios=scenarios,
        reverse_dcf=reverse,
        score=_empty_score("sector references have not yet been calculated"),
        retrieved_at=retrieved_at,
        sources=_valuation_sources(fundamental, prices, dcf_config),
        error=(
            fundamental.error
            if fundamental.status != DataStatus.AVAILABLE
            else currency_error
        ),
    )
    return _finalize_result(provisional, fundamental.data_quality, prices)


def score_valuation(
    result: ValuationAnalysisResult, *, minimum_coverage: float
) -> ValuationScore:
    """Score discounts to history/peers and base DCF; missing signals stay missing."""

    components: dict[str, ValuationScoreComponent] = {}
    for name in ("pe", "ev_ebitda", "price_fcf"):
        multiple = result.multiples.get(name)
        signals: dict[str, float | None] = {
            "historical_discount": None,
            "sector_discount": None,
        }
        signal_scores: list[float] = []
        if multiple and multiple.current.value is not None and multiple.current.value > 0:
            for reference_name, reference in (
                ("historical_discount", multiple.historical_median),
                ("sector_discount", multiple.sector_median),
            ):
                if reference.value is not None and reference.value > 0:
                    discount = reference.value / multiple.current.value - 1
                    signals[reference_name] = discount
                    signal_scores.append(_piecewise_discount_score(discount))
        component_score = (
            sum(signal_scores) / len(signal_scores) if signal_scores else None
        )
        components[name] = ValuationScoreComponent(
            name=name,
            score=round(component_score, 2) if component_score is not None else None,
            weight=SCORE_WEIGHTS[name],
            signals=signals,
            reason=None if signal_scores else "no positive historical or sector reference",
        )

    base = result.dcf_scenarios.get("base")
    dcf_discount = None
    if (
        base is not None
        and base.value_per_share is not None
        and result.valuation_price is not None
        and result.valuation_price > 0
    ):
        dcf_discount = base.value_per_share / result.valuation_price - 1
    components["dcf"] = ValuationScoreComponent(
        name="dcf",
        score=(
            round(_piecewise_discount_score(dcf_discount), 2)
            if dcf_discount is not None
            else None
        ),
        weight=SCORE_WEIGHTS["dcf"],
        signals={"base_dcf_margin_of_safety": dcf_discount},
        reason=None if dcf_discount is not None else "base DCF value is unavailable",
    )

    available = [component for component in components.values() if component.score is not None]
    coverage = sum(component.weight for component in available)
    observed = (
        sum(component.weight * component.score for component in available) / coverage
        if coverage
        else None
    )
    adjusted = sum(component.weight * (component.score or 0.0) for component in components.values())
    status = (
        DataStatus.AVAILABLE
        if observed is not None and coverage >= minimum_coverage
        else DataStatus.DATA_UNAVAILABLE
    )
    return ValuationScore(
        score=round(adjusted, 2) if status == DataStatus.AVAILABLE else None,
        observed_score=round(observed, 2) if observed is not None else None,
        coverage=round(coverage, 4),
        status=status,
        components=components,
        reason=(
            None
            if status == DataStatus.AVAILABLE
            else f"score coverage {coverage:.2%} is below required {minimum_coverage:.2%}"
        ),
    )


def _build_multiples(
    fundamental: FundamentalAnalysisResult,
    frame: pd.DataFrame,
    price: float | None,
    market_cap: float | None,
    market_cap_basis: str | None,
    minimum_history: int,
    currency_error: str | None,
) -> dict[str, ValuationMultiple]:
    history = {
        name: _historical_multiple_points(name, fundamental, frame, currency_error)
        for name in MULTIPLE_FORMULAS
    }
    current_values = {
        "pe": _safe_ratio(price, _metric_value(fundamental, "eps_diluted"), currency_error),
        "ev_ebitda": _safe_ratio(
            _enterprise_value(
                market_cap,
                _metric_value(fundamental, "debt"),
                _metric_value(fundamental, "cash"),
            ),
            _metric_value(fundamental, "ebitda_calculated"),
            currency_error,
        ),
        "price_fcf": _safe_ratio(
            market_cap,
            _metric_value(fundamental, "free_cash_flow"),
            currency_error,
        ),
    }
    return {
        name: ValuationMultiple(
            name=name,
            formula=formula,
            current=current_values[name],
            historical_median=_history_median(history[name], minimum_history),
            sector_median=MetricValue.unavailable("sector median not yet calculated"),
            history=history[name],
            market_cap_basis=market_cap_basis if name != "pe" else None,
        )
        for name, formula in MULTIPLE_FORMULAS.items()
    }


def _historical_multiple_points(
    name: str,
    fundamental: FundamentalAnalysisResult,
    frame: pd.DataFrame,
    currency_error: str | None,
) -> list[HistoricalMultiplePoint]:
    if currency_error:
        return []
    observations = fundamental.annual_observations
    period_ends = sorted(
        {item.end_date for values in observations.values() for item in values}
    )
    points: list[HistoricalMultiplePoint] = []
    for period_end in period_ends:
        if name == "pe":
            facts = _period_facts(observations, period_end, ("eps_diluted",))
            denominator = _fact_value(facts.get("eps_diluted"))
            basis = None
        else:
            shares_fact, shares_name = _shares_fact(observations, period_end, diluted_first=False)
            required = (
                ("operating_income", "depreciation_amortization", "cash")
                if name == "ev_ebitda"
                else ("operating_cash_flow", "capex")
            )
            facts = _period_facts(observations, period_end, required)
            if shares_fact is not None:
                facts[shares_name] = shares_fact
            denominator = None
            basis = f"price x {shares_name}" if shares_fact is not None else None
        if not facts or any(value is None for value in facts.values()):
            continue
        availability = max(fact.available_at for fact in facts.values() if fact is not None)
        price_row = _first_price_strictly_after(
            frame, availability.date(), fundamental.as_of.date()
        )
        historical_price = _row_price(price_row)
        price_date = _row_date(price_row)
        price_currency = _row_text(price_row, "currency")
        if (
            historical_price is None
            or price_date is None
            or (price_date - availability.date()).days > MAX_POST_FILING_PRICE_DELAY_DAYS
            or not price_currency
            or price_currency.upper() != "USD"
        ):
            continue
        if name == "pe":
            value = _positive_ratio(historical_price, denominator)
        else:
            shares = _fact_value(shares_fact)
            market_cap = historical_price * shares if shares is not None and shares > 0 else None
            if name == "ev_ebitda":
                debt_facts = _debt_facts(observations, period_end)
                if debt_facts is None:
                    continue
                facts.update(debt_facts)
                availability = max(fact.available_at for fact in facts.values() if fact is not None)
                price_row = _first_price_strictly_after(
                    frame, availability.date(), fundamental.as_of.date()
                )
                historical_price = _row_price(price_row)
                price_date = _row_date(price_row)
                price_currency = _row_text(price_row, "currency")
                if (
                    historical_price is None
                    or price_date is None
                    or shares is None
                    or (price_date - availability.date()).days
                    > MAX_POST_FILING_PRICE_DELAY_DAYS
                    or not price_currency
                    or price_currency.upper() != "USD"
                ):
                    continue
                market_cap = historical_price * shares
                debt = _debt_from_facts(debt_facts)
                cash = _fact_value(facts.get("cash"))
                ebitda = _sum_fact_values(
                    facts.get("operating_income"), facts.get("depreciation_amortization")
                )
                value = _positive_ratio(
                    _enterprise_value(market_cap, debt, cash), ebitda
                )
            else:
                free_cash_flow = _subtract_fact_values(
                    facts.get("operating_cash_flow"), facts.get("capex")
                )
                value = _positive_ratio(market_cap, free_cash_flow)
        if value is None or value <= 0:
            continue
        points.append(
            HistoricalMultiplePoint(
                value=value,
                fiscal_period_end=period_end,
                available_at=availability,
                price=historical_price,
                price_date=price_date,
                source_accessions=list(
                    dict.fromkeys(
                        fact.accession for fact in facts.values() if fact is not None
                    )
                ),
                market_cap_basis=basis,
            )
        )
    return points


def _build_dcf(
    fundamental: FundamentalAnalysisResult,
    config: SecurityValuationConfig | None,
    price: float | None,
    settings: ValuationSettings,
    currency_error: str | None,
) -> tuple[dict[str, DcfScenarioResult], ReverseDcfResult]:
    if config is None:
        reason = "no dated, sourced DCF assumptions configured for this ticker"
        return (
            {name: _unavailable_scenario(name, reason) for name in ("bear", "base", "bull")},
            _unavailable_reverse(settings, reason),
        )
    if config.assumption_date > fundamental.as_of.date():
        reason = "DCF assumptions were not available at the valuation cutoff"
        return (
            _unavailable_configured_scenarios(config, reason),
            _unavailable_reverse(settings, reason),
        )
    if currency_error:
        return (
            _unavailable_configured_scenarios(config, currency_error),
            _unavailable_reverse(settings, currency_error),
        )
    revenue = _metric_value(fundamental, "revenue")
    debt = _metric_value(fundamental, "debt")
    cash = _metric_value(fundamental, "cash")
    shares = _metric_value(fundamental, "diluted_shares") or _metric_value(
        fundamental, "shares_outstanding"
    )
    missing = [
        name
        for name, value in (("revenue", revenue), ("debt", debt), ("cash", cash), ("shares", shares))
        if value is None
    ]
    if missing:
        reason = "required DCF inputs unavailable: " + ", ".join(missing)
        return (
            _unavailable_configured_scenarios(config, reason),
            _unavailable_reverse(settings, reason),
        )
    scenarios: dict[str, DcfScenarioResult] = {}
    configured = {"bear": config.bear, "base": config.base, "bull": config.bull}
    if config.normalized is not None:
        configured["normalized"] = config.normalized
    for name, assumptions in configured.items():
        scenarios[name] = calculate_dcf(
            scenario=name,
            revenue=revenue,
            debt=debt,
            cash=cash,
            shares=shares,
            assumptions=assumptions,
            assumption_date=config.assumption_date,
            assumption_source=config.source,
        )
    reverse = (
        calculate_reverse_dcf(
            revenue=revenue,
            debt=debt,
            cash=cash,
            shares=shares,
            price=price,
            base_assumptions=config.base,
            assumption_date=config.assumption_date,
            assumption_source=config.source,
            lower_bound=settings.reverse_growth_lower_bound,
            upper_bound=settings.reverse_growth_upper_bound,
        )
        if price is not None
        else _unavailable_reverse(settings, "valuation price unavailable")
    )
    return scenarios, reverse


def _attach_sector_medians(
    results: dict[str, ValuationAnalysisResult], settings: ValuationSettings
) -> dict[str, ValuationAnalysisResult]:
    completed: dict[str, ValuationAnalysisResult] = {}
    for ticker, result in results.items():
        updated_multiples: dict[str, ValuationMultiple] = {}
        for name, multiple in result.multiples.items():
            peers = [
                other.multiples[name].current.value
                for other_ticker, other in results.items()
                if other_ticker != ticker
                and result.sector is not None
                and other.sector == result.sector
                and other.as_of == result.as_of
                and name in other.multiples
                and other.multiples[name].current.value is not None
                and other.multiples[name].current.value > 0
            ]
            sector = (
                MetricValue.available(median(peers))
                if len(peers) >= settings.sector_minimum_peers
                else MetricValue.unavailable(
                    f"{len(peers)} eligible peers; {settings.sector_minimum_peers} required"
                )
            )
            updated_multiples[name] = multiple.model_copy(
                update={"sector_median": sector, "sector_peer_count": len(peers)}
            )
        with_peers = result.model_copy(update={"multiples": updated_multiples})
        score = score_valuation(
            with_peers, minimum_coverage=settings.minimum_score_coverage
        )
        data_quality = with_peers.data_quality
        if score.coverage < 0.75 and data_quality == DataQuality.MEDIUM:
            data_quality = DataQuality.LOW
        completed[ticker] = with_peers.model_copy(
            update={"score": score, "data_quality": data_quality}
        )
    return completed


def _finalize_result(
    result: ValuationAnalysisResult,
    fundamental_quality: DataQuality,
    prices: PriceHistoryResult | None,
) -> ValuationAnalysisResult:
    has_value = any(
        multiple.current.value is not None for multiple in result.multiples.values()
    ) or any(
        scenario.value_per_share is not None for scenario in result.dcf_scenarios.values()
    )
    if not has_value:
        return result
    quality = (
        DataQuality.MEDIUM
        if fundamental_quality in {DataQuality.HIGH, DataQuality.MEDIUM}
        and prices is not None
        and prices.data_quality in {DataQuality.HIGH, DataQuality.MEDIUM}
        else DataQuality.LOW
    )
    return result.model_copy(update={"status": DataStatus.AVAILABLE, "data_quality": quality})


def _current_market_cap(
    security: Security,
    fundamental: FundamentalAnalysisResult,
    price: float | None,
    price_date: date | None,
    cutoff: date,
) -> tuple[float | None, str | None]:
    if (
        security.market_cap is not None
        and security.market_cap_observation_date is not None
        and security.market_cap_observation_date <= cutoff
        and security.market_cap_observation_date == price_date
        and security.market_cap_currency is not None
        and security.market_cap_currency.upper() == "USD"
    ):
        return security.market_cap, "configured market capitalization with provenance"
    shares = _metric_value(fundamental, "shares_outstanding")
    basis = "valuation close x SEC shares outstanding"
    if shares is None:
        shares = _metric_value(fundamental, "diluted_shares")
        basis = "valuation close x SEC diluted weighted-average shares"
    if price is None or shares is None or shares <= 0:
        return None, None
    return price * shares, basis


def _latest_price_on_or_before(frame: pd.DataFrame, cutoff: date):
    if frame.empty or "observation_date" not in frame or "close" not in frame:
        return None
    dates = pd.to_datetime(frame["observation_date"], errors="coerce")
    closes = pd.to_numeric(frame["close"], errors="coerce")
    eligible = frame.loc[
        dates.notna() & (dates.dt.date <= cutoff) & closes.notna() & (closes > 0)
    ].copy()
    if eligible.empty:
        return None
    eligible["_date"] = pd.to_datetime(eligible["observation_date"], errors="coerce")
    return eligible.sort_values("_date").iloc[-1]


def _first_price_strictly_after(
    frame: pd.DataFrame, cutoff: date, upper_cutoff: date
):
    if frame.empty or "observation_date" not in frame:
        return None
    dates = pd.to_datetime(frame["observation_date"], errors="coerce")
    eligible = frame.loc[
        (dates.dt.date > cutoff) & (dates.dt.date <= upper_cutoff)
    ].copy()
    if eligible.empty:
        return None
    eligible["_date"] = pd.to_datetime(eligible["observation_date"], errors="coerce")
    return eligible.sort_values("_date").iloc[0]


def _row_price(row) -> float | None:
    if row is None:
        return None
    value = pd.to_numeric(pd.Series([row.get("close")]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and value > 0 else None


def _row_date(row) -> date | None:
    if row is None:
        return None
    value = pd.to_datetime(row.get("observation_date"), errors="coerce")
    return value.date() if pd.notna(value) else None


def _row_text(row, key: str) -> str | None:
    if row is None:
        return None
    value = row.get(key)
    return str(value) if value is not None and pd.notna(value) else None


def _metric_value(result: FundamentalAnalysisResult, name: str) -> float | None:
    metric = result.metrics.get(name)
    return metric.value if metric is not None else None


def _safe_ratio(
    numerator: float | None,
    denominator: float | None,
    error: str | None = None,
) -> MetricValue:
    if error:
        return MetricValue.unavailable(error)
    value = _positive_ratio(numerator, denominator)
    if value is None:
        return MetricValue.unavailable("positive numerator and denominator are required")
    return MetricValue.available(value)


def _positive_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or numerator <= 0 or denominator <= 0:
        return None
    return numerator / denominator


def _enterprise_value(
    market_cap: float | None, debt: float | None, cash: float | None
) -> float | None:
    if market_cap is None or debt is None or cash is None:
        return None
    return market_cap + debt - cash


def _period_facts(
    observations: dict[str, list[FundamentalObservation]],
    period_end: date,
    names: Iterable[str],
) -> dict[str, FundamentalObservation | None]:
    return {
        name: next(
            (item for item in observations.get(name, []) if item.end_date == period_end),
            None,
        )
        for name in names
    }


def _shares_fact(
    observations: dict[str, list[FundamentalObservation]],
    period_end: date,
    *,
    diluted_first: bool,
) -> tuple[FundamentalObservation | None, str]:
    names = (
        ("diluted_shares", "shares_outstanding")
        if diluted_first
        else ("shares_outstanding", "diluted_shares")
    )
    for name in names:
        fact = _period_facts(observations, period_end, (name,))[name]
        if fact is not None:
            return fact, name
    return None, names[0]


def _debt_facts(
    observations: dict[str, list[FundamentalObservation]], period_end: date
) -> dict[str, FundamentalObservation] | None:
    direct = _period_facts(observations, period_end, ("long_term_debt_total",))[
        "long_term_debt_total"
    ]
    short = _period_facts(observations, period_end, ("short_term_borrowings",))[
        "short_term_borrowings"
    ]
    if direct is not None:
        result = {"long_term_debt_total": direct}
        if short is not None:
            result["short_term_borrowings"] = short
        return result
    parts = _period_facts(observations, period_end, ("current_debt", "noncurrent_debt"))
    if parts["current_debt"] is None or parts["noncurrent_debt"] is None:
        return None
    result = {name: fact for name, fact in parts.items() if fact is not None}
    if short is not None:
        result["short_term_borrowings"] = short
    return result


def _debt_from_facts(facts: dict[str, FundamentalObservation]) -> float:
    if "long_term_debt_total" in facts:
        debt = facts["long_term_debt_total"].value or 0.0
    else:
        debt = (facts["current_debt"].value or 0.0) + (
            facts["noncurrent_debt"].value or 0.0
        )
    if "short_term_borrowings" in facts:
        debt += facts["short_term_borrowings"].value or 0.0
    return debt


def _fact_value(fact: FundamentalObservation | None) -> float | None:
    return float(fact.value) if fact is not None and fact.value is not None else None


def _sum_fact_values(
    left: FundamentalObservation | None, right: FundamentalObservation | None
) -> float | None:
    left_value, right_value = _fact_value(left), _fact_value(right)
    return left_value + right_value if left_value is not None and right_value is not None else None


def _subtract_fact_values(
    left: FundamentalObservation | None, right: FundamentalObservation | None
) -> float | None:
    left_value, right_value = _fact_value(left), _fact_value(right)
    return left_value - right_value if left_value is not None and right_value is not None else None


def _history_median(
    points: list[HistoricalMultiplePoint], minimum: int
) -> MetricValue:
    if len(points) < minimum:
        return MetricValue.unavailable(f"{len(points)} historical points; {minimum} required")
    return MetricValue.available(median(point.value for point in points))


def _piecewise_discount_score(value: float) -> float:
    if value <= DISCOUNT_SCORE_BANDS[0][0]:
        return DISCOUNT_SCORE_BANDS[0][1]
    if value >= DISCOUNT_SCORE_BANDS[-1][0]:
        return DISCOUNT_SCORE_BANDS[-1][1]
    for (x0, y0), (x1, y1) in zip(DISCOUNT_SCORE_BANDS, DISCOUNT_SCORE_BANDS[1:]):
        if x0 <= value <= x1:
            return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    raise AssertionError("discount score bands are not exhaustive")


def _unavailable_scenario(name: str, reason: str) -> DcfScenarioResult:
    return DcfScenarioResult(
        scenario=name, status=DataStatus.DATA_UNAVAILABLE, reason=reason
    )


def _unavailable_configured_scenarios(
    config: SecurityValuationConfig, reason: str
) -> dict[str, DcfScenarioResult]:
    configured = {"bear": config.bear, "base": config.base, "bull": config.bull}
    if config.normalized is not None:
        configured["normalized"] = config.normalized
    return {
        name: DcfScenarioResult(
            scenario=name,
            status=DataStatus.DATA_UNAVAILABLE,
            assumption_date=config.assumption_date,
            assumption_source=config.source,
            assumptions=assumptions.model_dump(mode="json"),
            reason=reason,
        )
        for name, assumptions in configured.items()
    }


def _unavailable_reverse(
    settings: ValuationSettings, reason: str
) -> ReverseDcfResult:
    return ReverseDcfResult(
        status=DataStatus.DATA_UNAVAILABLE,
        lower_bound=settings.reverse_growth_lower_bound,
        upper_bound=settings.reverse_growth_upper_bound,
        reason=reason,
    )


def _empty_score(reason: str) -> ValuationScore:
    return ValuationScore(
        score=None,
        observed_score=None,
        coverage=0.0,
        status=DataStatus.DATA_UNAVAILABLE,
        reason=reason,
    )


def _valuation_sources(
    fundamental: FundamentalAnalysisResult,
    prices: PriceHistoryResult | None,
    config: SecurityValuationConfig | None,
) -> list[dict[str, object]]:
    sources = [{**source, "role": "valuation_fundamentals"} for source in fundamental.sources]
    if prices is not None:
        sources.append(
            {
                "source": prices.source,
                "source_url": prices.source_url,
                "role": "valuation_prices",
            }
        )
    if config is not None:
        sources.append(
            {
                "source": config.source,
                "observation_date": config.assumption_date.isoformat(),
                "notes": config.notes,
                "role": "dcf_assumptions",
            }
        )
    return sources
