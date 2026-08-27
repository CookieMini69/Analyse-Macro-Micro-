from pathlib import Path

import numpy as np

from src.config import load_settings
from src.data.sources import PriceHistoryResult
from src.models import DataQuality, DataStatus, Security
from src.pipeline import run_pipeline
from tests.factories import price_frame
from tests.test_fundamental_analysis import complete_data


class FakePriceSource:
    def fetch(self, security: Security, *, period: str = "max") -> PriceHistoryResult:
        prices = np.concatenate([np.full(250, 100.0), np.linspace(100, 60, 50)])
        return PriceHistoryResult(
            security=security,
            frame=price_frame(prices, ticker=security.ticker),
            status=DataStatus.AVAILABLE,
            data_quality=DataQuality.MEDIUM,
            source="synthetic_test_fixture",
            source_url=None,
        )


class BrokenPriceSource:
    def fetch(self, security: Security, *, period: str = "max") -> PriceHistoryResult:
        raise RuntimeError("synthetic provider failure")


class FakeFundamentalSource:
    def fetch(self, security: Security, *, as_of=None):
        data = complete_data()
        data.security = security
        data.cik = "0000000001"
        return data


def write_configuration(tmp_path: Path) -> None:
    (tmp_path / "universe.yaml").write_text(
        """
version: 1
filters: {}
securities:
  - ticker: TEST
    company: Test Fixture Only
    country: France
    currency: EUR
""",
        encoding="utf-8",
    )
    (tmp_path / "settings.yaml").write_text(
        f"""
project_root: "{tmp_path.as_posix()}"
paths:
  universe: universe.yaml
  raw_data: raw
  processed_data: processed
  cache: cache
  reports: reports
price:
  provider: yahoo
  history_period: max
  cache_ttl_hours: 1
  max_workers: 1
  confidence: 0.8
screening:
  drawdown_52w_threshold: -0.20
  drawdown_3m_threshold: -0.15
  drawdown_6m_threshold: -0.20
  relative_sector_threshold: -0.10
  minimum_observations: 60
  rsi_period: 14
  annualization_days: 252
export:
  csv: true
  excel: true
  filename_prefix: test_scan
logging:
  level: WARNING
""",
        encoding="utf-8",
    )


def test_offline_pipeline_runs_end_to_end(tmp_path: Path) -> None:
    write_configuration(tmp_path)
    settings = load_settings(tmp_path / "settings.yaml")
    output = run_pipeline(settings, price_source=FakePriceSource())
    assert len(output.results) == 1
    assert output.results[0].is_candidate is True
    assert len(output.exported_files) == 2
    assert (tmp_path / "processed" / "prices" / "TEST.csv").exists()


def test_provider_exception_is_exported_as_unavailable_row(tmp_path: Path) -> None:
    write_configuration(tmp_path)
    settings = load_settings(tmp_path / "settings.yaml")
    output = run_pipeline(settings, price_source=BrokenPriceSource())
    assert len(output.results) == 1
    assert output.results[0].current_price is None
    assert output.results[0].is_candidate is False
    assert "TEST" in output.download_errors


def test_pipeline_enriches_scan_with_point_in_time_fundamentals(tmp_path: Path) -> None:
    write_configuration(tmp_path)
    (tmp_path / "universe.yaml").write_text(
        """
version: 1
filters: {}
securities:
  - ticker: TEST
    cik: "1"
    company: Test Fixture Only
    country: United States
    currency: USD
""",
        encoding="utf-8",
    )
    (tmp_path / "valuation.yaml").write_text(
        """
version: 1
securities:
  TEST:
    assumption_date: 2025-01-01
    source: synthetic documented integration-test assumptions
    bear: &scenario
      projection_years: 3
      revenue_growth: 0.05
      operating_margin: 0.15
      tax_rate: 0.25
      depreciation_margin: 0.03
      capex_margin: 0.05
      working_capital_investment_margin: 0.01
      wacc: 0.09
      terminal_growth: 0.02
    base: *scenario
    bull: *scenario
""",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path / "settings.yaml")
    settings.paths.valuation = tmp_path / "valuation.yaml"
    output = run_pipeline(
        settings,
        price_source=FakePriceSource(),
        fundamental_source=FakeFundamentalSource(),
        fundamentals_as_of="2025-03-01T00:00:00Z",
    )
    scan = output.results[0]
    assert scan.fundamental_status == DataStatus.AVAILABLE
    assert scan.fundamental_quality_score is not None
    assert scan.fundamental_quality_coverage == 1.0
    assert scan.fundamental_metrics["free_cash_flow"] == 12.0
    assert len(output.fundamental_exported_files) == 2
    assert scan.valuation_status == DataStatus.AVAILABLE
    assert np.isclose(scan.pe_current, 60.0 / 1.21)
    assert scan.dcf_base_value_per_share is not None
    assert scan.valuation_coverage == 0.4
    assert scan.valuation_score is None
    assert len(output.valuation_exported_files) == 2


def test_missing_sec_identity_is_explicit_and_does_not_abort_prices(
    tmp_path: Path, monkeypatch
) -> None:
    write_configuration(tmp_path)
    (tmp_path / "universe.yaml").write_text(
        """
version: 1
filters: {}
securities:
  - ticker: TEST
    cik: "1"
    country: United States
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    settings = load_settings(tmp_path / "settings.yaml")
    output = run_pipeline(settings, price_source=FakePriceSource())
    assert output.results[0].current_price == 60.0
    assert output.results[0].fundamental_status == DataStatus.DATA_UNAVAILABLE
    assert "SEC_USER_AGENT" in output.fundamental_errors["TEST"]
