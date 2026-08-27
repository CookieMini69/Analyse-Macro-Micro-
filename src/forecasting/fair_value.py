"""Pure DCF and reverse-DCF calculations with no implicit assumptions."""

from __future__ import annotations

from datetime import date

from src.models import (
    DataStatus,
    DcfProjectionYear,
    DcfScenarioResult,
    ReverseDcfResult,
)
from src.valuation_config import DcfAssumptions


def calculate_dcf(
    *,
    scenario: str,
    revenue: float,
    debt: float,
    cash: float,
    shares: float,
    assumptions: DcfAssumptions,
    assumption_date: date,
    assumption_source: str,
) -> DcfScenarioResult:
    """Discount explicit UFCF projections and a Gordon-growth terminal value."""

    if revenue <= 0:
        return _unavailable_dcf(
            scenario,
            "revenue must be positive",
            assumptions,
            assumption_date,
            assumption_source,
        )
    if shares <= 0:
        return _unavailable_dcf(
            scenario,
            "share count must be positive",
            assumptions,
            assumption_date,
            assumption_source,
        )
    if debt < 0 or cash < 0:
        return _unavailable_dcf(
            scenario,
            "debt and cash cannot be negative",
            assumptions,
            assumption_date,
            assumption_source,
        )

    growth = assumptions.expanded("revenue_growth")
    margin = assumptions.expanded("operating_margin")
    tax = assumptions.expanded("tax_rate")
    depreciation = assumptions.expanded("depreciation_margin")
    capex = assumptions.expanded("capex_margin")
    working_capital = assumptions.expanded("working_capital_investment_margin")
    projections: list[DcfProjectionYear] = []
    projected_revenue = float(revenue)
    projected_cash_flow_pv = 0.0
    for index in range(assumptions.projection_years):
        projected_revenue *= 1 + growth[index]
        ebit = projected_revenue * margin[index]
        nopat = ebit * (1 - tax[index])
        depreciation_value = projected_revenue * depreciation[index]
        capex_value = projected_revenue * capex[index]
        working_capital_value = projected_revenue * working_capital[index]
        cash_flow = (
            nopat
            + depreciation_value
            - capex_value
            - working_capital_value
        )
        discount_factor = 1 / (1 + assumptions.wacc) ** (index + 1)
        present_value = cash_flow * discount_factor
        projected_cash_flow_pv += present_value
        projections.append(
            DcfProjectionYear(
                year=index + 1,
                revenue=projected_revenue,
                ebit=ebit,
                nopat=nopat,
                depreciation_amortization=depreciation_value,
                capex=capex_value,
                working_capital_investment=working_capital_value,
                unlevered_free_cash_flow=cash_flow,
                discount_factor=discount_factor,
                present_value=present_value,
            )
        )

    terminal_cash_flow = projections[-1].unlevered_free_cash_flow * (
        1 + assumptions.terminal_growth
    )
    terminal_value = terminal_cash_flow / (
        assumptions.wacc - assumptions.terminal_growth
    )
    terminal_pv = terminal_value / (
        (1 + assumptions.wacc) ** assumptions.projection_years
    )
    enterprise_value = projected_cash_flow_pv + terminal_pv
    equity_value = enterprise_value - debt + cash
    value_per_share = equity_value / shares
    if enterprise_value <= 0 or equity_value <= 0 or value_per_share <= 0:
        return _unavailable_dcf(
            scenario,
            "explicit assumptions produce a non-positive enterprise or equity value",
            assumptions,
            assumption_date,
            assumption_source,
        )
    return DcfScenarioResult(
        scenario=scenario,
        status=DataStatus.AVAILABLE,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        terminal_value=terminal_value,
        terminal_value_present_value=terminal_pv,
        projected_cash_flow_present_value=projected_cash_flow_pv,
        assumption_date=assumption_date,
        assumption_source=assumption_source,
        assumptions=assumptions.model_dump(mode="json"),
        projections=projections,
    )


def calculate_reverse_dcf(
    *,
    revenue: float,
    debt: float,
    cash: float,
    shares: float,
    price: float,
    base_assumptions: DcfAssumptions,
    assumption_date: date,
    assumption_source: str,
    lower_bound: float,
    upper_bound: float,
    tolerance: float = 1e-7,
    max_iterations: int = 100,
) -> ReverseDcfResult:
    """Solve for a constant annual revenue growth rate implied by market EV."""

    target = price * shares + debt - cash
    if revenue <= 0 or shares <= 0 or price <= 0 or target <= 0:
        return ReverseDcfResult(
            status=DataStatus.DATA_UNAVAILABLE,
            target_enterprise_value=target if target > 0 else None,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            reason="positive revenue, shares, price, and target enterprise value are required",
        )

    def enterprise_value(growth: float) -> float | None:
        assumptions = base_assumptions.model_copy(
            update={"revenue_growth": growth}
        )
        result = calculate_dcf(
            scenario="reverse_dcf_trial",
            revenue=revenue,
            debt=0.0,
            cash=0.0,
            shares=1.0,
            assumptions=assumptions,
            assumption_date=assumption_date,
            assumption_source=assumption_source,
        )
        return result.enterprise_value

    low_value = enterprise_value(lower_bound)
    high_value = enterprise_value(upper_bound)
    if low_value is None or high_value is None:
        return ReverseDcfResult(
            status=DataStatus.DATA_UNAVAILABLE,
            target_enterprise_value=target,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            reason="reverse DCF bounds produce invalid enterprise values",
        )
    low_error = low_value - target
    high_error = high_value - target
    if low_error == 0:
        return _solved_reverse(lower_bound, target, low_value, lower_bound, upper_bound, 0)
    if high_error == 0:
        return _solved_reverse(upper_bound, target, high_value, lower_bound, upper_bound, 0)
    if low_error * high_error > 0:
        return ReverseDcfResult(
            status=DataStatus.DATA_UNAVAILABLE,
            target_enterprise_value=target,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            reason="market enterprise value is not bracketed by configured growth bounds",
        )

    low, high = lower_bound, upper_bound
    solved_value = low_value
    midpoint = low
    for iteration in range(1, max_iterations + 1):
        midpoint = (low + high) / 2
        trial = enterprise_value(midpoint)
        if trial is None:
            break
        solved_value = trial
        error = trial - target
        if abs(error) <= max(1.0, abs(target)) * tolerance:
            return _solved_reverse(
                midpoint, target, trial, lower_bound, upper_bound, iteration
            )
        if low_error * error <= 0:
            high = midpoint
        else:
            low = midpoint
            low_error = error
    if solved_value is not None and abs(solved_value - target) <= max(1.0, abs(target)) * 1e-5:
        return _solved_reverse(
            midpoint, target, solved_value, lower_bound, upper_bound, max_iterations
        )
    return ReverseDcfResult(
        status=DataStatus.DATA_UNAVAILABLE,
        target_enterprise_value=target,
        solved_enterprise_value=solved_value,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        iterations=max_iterations,
        reason="reverse DCF did not converge",
    )


def _unavailable_dcf(
    scenario: str,
    reason: str,
    assumptions: DcfAssumptions,
    assumption_date: date,
    assumption_source: str,
) -> DcfScenarioResult:
    return DcfScenarioResult(
        scenario=scenario,
        status=DataStatus.DATA_UNAVAILABLE,
        assumption_date=assumption_date,
        assumption_source=assumption_source,
        assumptions=assumptions.model_dump(mode="json"),
        reason=reason,
    )


def _solved_reverse(
    growth: float,
    target: float,
    solved: float,
    lower: float,
    upper: float,
    iterations: int,
) -> ReverseDcfResult:
    return ReverseDcfResult(
        implied_revenue_growth=growth,
        target_enterprise_value=target,
        solved_enterprise_value=solved,
        status=DataStatus.AVAILABLE,
        lower_bound=lower,
        upper_bound=upper,
        iterations=iterations,
    )
