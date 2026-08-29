from datetime import UTC, date, datetime

import numpy as np
import pytest
from pydantic import ValidationError

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.valuation import analyze_valuation, analyze_valuations
from src.config import ValuationSettings
from src.data.sources import PriceHistoryResult
from src.forecasting.fair_value import calculate_dcf, calculate_reverse_dcf
from src.models import DataQuality, DataStatus, Security
from src.valuation_config import DcfAssumptions, SecurityValuationConfig, ValuationConfig
from tests.factories import price_frame
from tests.test_fundamental_analysis import complete_data


def assumptions(*, growth: float = 0.0) -> DcfAssumptions:
    return DcfAssumptions(
        projection_years=1,
        revenue_growth=growth,
        operating_margin=0.20,
        tax_rate=0.25,
        depreciation_margin=0.02,
        capex_margin=0.03,
        working_capital_investment_margin=0.01,
        wacc=0.10,
        terminal_growth=0.0,
    )


def valuation_config(*, assumption_date: date = date(2025, 1, 1)) -> SecurityValuationConfig:
    return SecurityValuationConfig(
        assumption_date=assumption_date,
        source="synthetic, documented test assumptions",
        bear=assumptions(growth=-0.05),
        base=assumptions(growth=0.05),
        bull=assumptions(growth=0.10),
        normalized=assumptions(growth=0.03),
    )


def priced_security(ticker: str = "TEST", *, price: float = 20.0) -> tuple[Security, PriceHistoryResult]:
    security = Security(
        ticker=ticker,
        cik="1",
        country="United States",
        sector="Software",
        currency="USD",
    )
    frame = price_frame(
        np.full(550, price), ticker=ticker, start="2023-02-01"
    )
    return security, PriceHistoryResult(
        security=security,
        frame=frame,
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        source="synthetic_test_fixture",
        source_url=None,
    )


def fundamental_for(security: Security):
    data = complete_data()
    data.security = security
    return analyze_fundamentals(data)


def test_dcf_calculation_has_auditable_cash_flow_bridge() -> None:
    result = calculate_dcf(
        scenario="base",
        revenue=100.0,
        debt=10.0,
        cash=5.0,
        shares=10.0,
        assumptions=assumptions(),
        assumption_date=date(2025, 1, 1),
        assumption_source="synthetic test",
    )
    assert result.status == DataStatus.AVAILABLE
    assert result.projections[0].unlevered_free_cash_flow == pytest.approx(13.0)
    assert result.enterprise_value == pytest.approx(130.0)
    assert result.value_per_share == pytest.approx(12.5)


def test_reverse_dcf_recovers_known_constant_growth() -> None:
    known = calculate_dcf(
        scenario="known",
        revenue=100.0,
        debt=10.0,
        cash=5.0,
        shares=10.0,
        assumptions=assumptions(growth=0.05),
        assumption_date=date(2025, 1, 1),
        assumption_source="synthetic test",
    )
    reverse = calculate_reverse_dcf(
        revenue=100.0,
        debt=10.0,
        cash=5.0,
        shares=10.0,
        price=known.value_per_share,
        base_assumptions=assumptions(growth=0.0),
        assumption_date=date(2025, 1, 1),
        assumption_source="synthetic test",
        lower_bound=-0.50,
        upper_bound=0.50,
    )
    assert reverse.status == DataStatus.AVAILABLE
    assert reverse.implied_revenue_growth == pytest.approx(0.05, abs=1e-6)


def test_dcf_configuration_rejects_terminal_growth_at_or_above_wacc() -> None:
    with pytest.raises(ValidationError, match="wacc must be strictly greater"):
        DcfAssumptions(
            **{
                **assumptions().model_dump(),
                "wacc": 0.05,
                "terminal_growth": 0.05,
            }
        )


def test_multiples_use_price_at_cutoff_and_first_close_after_publication() -> None:
    security, prices = priced_security(price=20.0)
    fundamental = fundamental_for(security)
    result = analyze_valuation(
        security,
        fundamental,
        prices,
        None,
        ValuationSettings(historical_minimum_points=3),
    )
    assert result.valuation_price_date <= fundamental.as_of.date()
    assert result.multiples["pe"].current.value == pytest.approx(20.0 / 1.21)
    assert result.multiples["ev_ebitda"].current.value == pytest.approx(
        (200.0 + 28.0 - 24.0) / (18.15 + 3.6)
    )
    assert result.multiples["price_fcf"].current.value == pytest.approx(200.0 / 12.0)
    assert result.multiples["pe"].historical_median.status == DataStatus.AVAILABLE
    assert result.multiples["pe"].historical_median.value == pytest.approx(20.0 / 1.1)
    first = result.multiples["pe"].history[0]
    assert first.available_at == datetime(2023, 2, 1, 20, tzinfo=UTC)
    assert first.price_date == date(2023, 2, 2)
    assert result.dcf_scenarios["base"].status == DataStatus.DATA_UNAVAILABLE
    assert "no dated" in result.dcf_scenarios["base"].reason


def test_current_valuation_skips_incomplete_latest_market_bar() -> None:
    security, prices = priced_security(price=20.0)
    fundamental = fundamental_for(security)
    eligible = prices.frame[
        prices.frame["observation_date"].dt.date <= fundamental.as_of.date()
    ]
    latest_eligible_index = eligible.index[-1]
    previous_date = eligible.iloc[-2]["observation_date"].date()
    prices.frame.loc[latest_eligible_index, ["close", "adjusted_close"]] = np.nan
    result = analyze_valuation(
        security, fundamental, prices, None, ValuationSettings()
    )
    assert result.valuation_price == pytest.approx(20.0)
    assert result.valuation_price_date == previous_date
    assert result.status == DataStatus.AVAILABLE


def test_valuation_rejects_unconverted_local_currency_fundamentals() -> None:
    security, prices = priced_security(price=20.0)
    fundamental = fundamental_for(security)
    local_observations = {
        name: [
            observation.model_copy(
                update={
                    "unit": (
                        "DKK/shares"
                        if observation.unit == "USD/shares"
                        else "DKK" if observation.unit == "USD" else observation.unit
                    ),
                    "currency": (
                        "DKK" if observation.unit in {"USD", "USD/shares"} else observation.currency
                    ),
                }
            )
            for observation in observations
        ]
        for name, observations in fundamental.annual_observations.items()
    }
    fundamental = fundamental.model_copy(
        update={"annual_observations": local_observations}
    )
    result = analyze_valuation(
        security, fundamental, prices, None, ValuationSettings()
    )
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert "fundamental fact currency 'DKK'" in result.error
    assert all(
        multiple.current.status == DataStatus.DATA_UNAVAILABLE
        for multiple in result.multiples.values()
    )


def test_historical_multiple_never_uses_a_post_cutoff_close() -> None:
    security, prices = priced_security(price=20.0)
    fundamental = fundamental_for(security)
    fundamental = fundamental.model_copy(
        update={"as_of": datetime(2025, 2, 1, 21, tzinfo=UTC)}
    )
    result = analyze_valuation(
        security,
        fundamental,
        prices,
        None,
        ValuationSettings(historical_minimum_points=1),
    )
    assert all(
        point.price_date <= fundamental.as_of.date()
        for point in result.multiples["pe"].history
    )
    assert date(2024, 12, 31) not in {
        point.fiscal_period_end for point in result.multiples["pe"].history
    }


def test_future_dcf_assumptions_are_not_used() -> None:
    security, prices = priced_security()
    fundamental = fundamental_for(security)
    result = analyze_valuation(
        security,
        fundamental,
        prices,
        valuation_config(assumption_date=date(2025, 3, 2)),
        ValuationSettings(),
    )
    assert result.dcf_scenarios["base"].status == DataStatus.DATA_UNAVAILABLE
    assert "not available at the valuation cutoff" in result.dcf_scenarios["base"].reason


def test_sector_median_excludes_the_target_security() -> None:
    first_security, first_prices = priced_security("ONE", price=10.0)
    second_security, second_prices = priced_security("TWO", price=30.0)
    fundamentals = {
        "ONE": fundamental_for(first_security),
        "TWO": fundamental_for(second_security),
    }
    results = analyze_valuations(
        [first_security, second_security],
        fundamentals,
        {"ONE": first_prices, "TWO": second_prices},
        ValuationConfig(),
        ValuationSettings(sector_minimum_peers=1, historical_minimum_points=3),
    )
    assert results["ONE"].multiples["pe"].sector_peer_count == 1
    assert results["ONE"].multiples["pe"].sector_median.value == pytest.approx(
        results["TWO"].multiples["pe"].current.value
    )
    assert results["ONE"].score.coverage == pytest.approx(0.6)
    assert results["ONE"].score.status == DataStatus.AVAILABLE


def test_configured_dcf_includes_bear_base_bull_normalized_and_reverse() -> None:
    security, prices = priced_security(price=20.0)
    result = analyze_valuation(
        security,
        fundamental_for(security),
        prices,
        valuation_config(),
        ValuationSettings(),
    )
    assert set(result.dcf_scenarios) == {"bear", "base", "bull", "normalized"}
    assert all(item.status == DataStatus.AVAILABLE for item in result.dcf_scenarios.values())
    assert result.dcf_scenarios["bear"].value_per_share < result.dcf_scenarios["bull"].value_per_share
    assert result.reverse_dcf is not None
