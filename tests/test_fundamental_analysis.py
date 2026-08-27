from datetime import UTC, date, datetime

import pytest

from src.analysis.fundamentals import analyze_fundamentals, score_fundamental_quality
from src.data.fundamentals import FundamentalDataResult
from src.models import (
    AvailabilityPrecision,
    CalculatedFundamentalMetric,
    DataQuality,
    DataStatus,
    FundamentalObservation,
    Security,
)


def observation(
    name: str,
    value: float,
    year: int,
    *,
    instant: bool = False,
    unit: str = "USD",
) -> FundamentalObservation:
    accession = f"0000000000-{str(year)[-2:]}-000001"
    end = date(year, 12, 31)
    return FundamentalObservation(
        name=name,
        value=value,
        taxonomy="us-gaap",
        concept=f"Synthetic{name}",
        unit=unit,
        currency="USD" if unit.startswith("USD") else None,
        start_date=None if instant else date(year, 1, 1),
        end_date=end,
        fiscal_year=year,
        fiscal_period="FY",
        form="10-K",
        accession=accession,
        filed_date=date(year + 1, 2, 1),
        accepted_at=datetime(year + 1, 2, 1, 20, tzinfo=UTC),
        available_at=datetime(year + 1, 2, 1, 20, tzinfo=UTC),
        availability_precision=AvailabilityPrecision.ACCEPTANCE_TIMESTAMP,
        source_url=f"https://www.sec.gov/Archives/test/{accession}",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=1.0,
    )


def complete_data(*, include_capex: bool = True) -> FundamentalDataResult:
    annual_values = {
        "revenue": [100.0, 110.0, 121.0],
        "gross_profit": [40.0, 44.0, 48.4],
        "operating_income": [15.0, 16.5, 18.15],
        "net_income": [10.0, 11.0, 12.1],
        "eps_diluted": [1.0, 1.1, 1.21],
        "operating_cash_flow": [15.0, 16.5, 18.0],
        "depreciation_amortization": [3.0, 3.3, 3.6],
        "interest_expense": [2.0, 2.0, 2.0],
        "pretax_income": [14.0, 15.0, 16.0],
        "income_tax_expense": [3.0, 3.2, 3.4],
        "diluted_shares": [10.0, 10.0, 10.0],
    }
    if include_capex:
        annual_values["capex"] = [5.0, 5.5, 6.0]
    instant_values = {
        "cash": [20.0, 22.0, 24.0],
        "equity": [50.0, 55.0, 60.0],
        "current_assets": [40.0, 44.0, 48.0],
        "current_liabilities": [20.0, 21.0, 22.0],
        "long_term_debt_total": [30.0, 29.0, 28.0],
        "shares_outstanding": [10.0, 10.0, 10.0],
    }
    observations = {
        name: [observation(name, value, year) for year, value in zip((2022, 2023, 2024), values)]
        for name, values in annual_values.items()
    }
    observations.update(
        {
            name: [
                observation(name, value, year, instant=True, unit="shares" if "shares" in name else "USD")
                for year, value in zip((2022, 2023, 2024), values)
            ]
            for name, values in instant_values.items()
        }
    )
    return FundamentalDataResult(
        security=Security(ticker="TEST", cik="1", country="United States"),
        cik="0000000001",
        company="Synthetic Test Fixture",
        as_of=datetime(2025, 3, 1, tzinfo=UTC),
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        observations=observations,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        sources=[{"name": "synthetic_test_fixture"}],
    )


def test_calculates_growth_profitability_balance_and_cash_flow() -> None:
    result = analyze_fundamentals(complete_data())
    metrics = result.metrics
    assert metrics["free_cash_flow"].value == pytest.approx(12.0)
    assert metrics["fcf_margin"].value == pytest.approx(12.0 / 121.0)
    assert metrics["operating_margin"].value == pytest.approx(0.15)
    assert metrics["revenue_cagr"].value == pytest.approx(0.10, abs=0.001)
    assert metrics["roe"].value == pytest.approx(12.1 / 57.5)
    assert metrics["debt_to_equity"].value == pytest.approx(28.0 / 60.0)
    assert metrics["fcf_per_share"].value == pytest.approx(1.2)
    assert metrics["roic"].value is not None
    assert result.quality_score.status == DataStatus.AVAILABLE
    assert result.quality_score.coverage == 1.0
    assert result.quality_score.score is not None


def test_missing_capex_is_not_silently_imputed() -> None:
    result = analyze_fundamentals(complete_data(include_capex=False))
    assert result.metrics["free_cash_flow"].value is None
    assert result.metrics["free_cash_flow"].status == DataStatus.DATA_UNAVAILABLE
    assert result.metrics["fcf_margin"].value is None
    assert result.quality_score.coverage < 1.0


def available_metric(name: str, value: float) -> CalculatedFundamentalMetric:
    return CalculatedFundamentalMetric(
        name=name,
        value=value,
        unit="ratio",
        status=DataStatus.AVAILABLE,
    )


def test_quality_score_stays_null_below_coverage_threshold() -> None:
    metrics = {
        "revenue_cagr": available_metric("revenue_cagr", 0.10),
        "eps_cagr": available_metric("eps_cagr", 0.10),
        "ebitda_cagr": available_metric("ebitda_cagr", 0.10),
        "fcf_cagr": available_metric("fcf_cagr", 0.10),
    }
    score = score_fundamental_quality(metrics, minimum_coverage=0.50)
    assert score.coverage == 0.25
    assert score.observed_score is not None
    assert score.score is None
    assert score.status == DataStatus.DATA_UNAVAILABLE

