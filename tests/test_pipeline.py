from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import load_settings
from src.data.sources import PriceHistoryResult
from src.models import (
    DataQuality,
    DataStatus,
    MacroObservation,
    MacroSeriesResult,
    NewsArticle,
    NewsSearchResult,
    Security,
    ShockCategory,
    ShockNature,
)
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


class FakeMacroSource:
    def fetch(self, series_key, definition, *, as_of=None, history_years=2):
        cutoff = as_of
        retrieved = datetime(2025, 3, 1, 12, tzinfo=UTC)
        observations = [
            MacroObservation(
                series_key=series_key,
                series_id=definition.series_id,
                series_title=definition.name,
                value=value,
                observation_date=observation_date,
                realtime_start=date(2025, 3, 1),
                realtime_end=date(9999, 12, 31),
                as_of=cutoff,
                frequency="Daily",
                unit="Synthetic index",
                source_url="https://fred.stlouisfed.org/series/SYNTH",
                retrieved_at=retrieved,
            )
            for observation_date, value in (
                (date(2025, 1, 28), 100.0),
                (date(2025, 2, 28), 110.0),
            )
        ]
        return MacroSeriesResult(
            series_key=series_key,
            series_id=definition.series_id,
            configured_name=definition.name,
            as_of=cutoff,
            status=DataStatus.AVAILABLE,
            data_quality=DataQuality.MEDIUM,
            observations=observations,
            retrieved_at=retrieved,
            source_url="https://fred.stlouisfed.org/series/SYNTH",
        )


class FakeNewsSource:
    def fetch(self, security, *, as_of=None, lookback_days=30, max_articles=75):
        articles = [
            NewsArticle(
                title="Synthetic outage resolved after temporary disruption",
                url="https://one.test/synthetic-1",
                source_domain="one.test",
                seen_at=as_of - timedelta(days=2),
                query='"Synthetic Test Fixture Only"',
                index_source_url="https://api.gdeltproject.org/synthetic-test-only",
                retrieved_at=as_of,
            ),
            NewsArticle(
                title="Synthetic operations restarted and restored",
                url="https://two.test/synthetic-2",
                source_domain="two.test",
                seen_at=as_of - timedelta(days=1),
                query='"Synthetic Test Fixture Only"',
                index_source_url="https://api.gdeltproject.org/synthetic-test-only",
                retrieved_at=as_of,
            ),
        ]
        return NewsSearchResult(
            ticker=security.ticker,
            company=security.company,
            query='"Synthetic Test Fixture Only"',
            window_start=as_of - timedelta(days=lookback_days),
            as_of=as_of,
            status=DataStatus.AVAILABLE,
            data_quality=DataQuality.MEDIUM,
            articles=articles,
            retrieved_at=as_of,
            source_url="https://api.gdeltproject.org/synthetic-test-only",
        )


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
    assert "TEST" in output.historical_results
    assert len(output.historical_exported_files) == 2


def test_provider_exception_is_exported_as_unavailable_row(tmp_path: Path) -> None:
    write_configuration(tmp_path)
    settings = load_settings(tmp_path / "settings.yaml")
    output = run_pipeline(settings, price_source=BrokenPriceSource())
    assert len(output.results) == 1
    assert output.results[0].current_price is None
    assert output.results[0].is_candidate is False
    assert "TEST" in output.download_errors


def test_historical_cutoff_filters_price_scan_and_persisted_history(
    tmp_path: Path,
) -> None:
    write_configuration(tmp_path)
    settings = load_settings(tmp_path / "settings.yaml")
    cutoff = datetime(2024, 6, 28, 12, 0, tzinfo=UTC)
    settings.fundamentals.as_of = cutoff

    output = run_pipeline(settings, price_source=FakePriceSource())

    result = output.results[0]
    assert result.observation_date is not None
    assert result.observation_date < cutoff.date()
    assert result.current_price == 100.0
    assert result.is_candidate is False
    persisted = pd.read_csv(tmp_path / "processed" / "prices" / "TEST.csv")
    assert pd.to_datetime(persisted["observation_date"]).dt.date.max() < cutoff.date()


def test_cutoff_before_price_history_is_explicitly_unavailable(tmp_path: Path) -> None:
    write_configuration(tmp_path)
    settings = load_settings(tmp_path / "settings.yaml")

    output = run_pipeline(
        settings,
        price_source=FakePriceSource(),
        fundamentals_as_of="2020-01-01",
    )

    result = output.results[0]
    assert result.current_price is None
    assert result.is_candidate is False
    assert "point-in-time cutoff" in output.download_errors["TEST"]
    assert not (tmp_path / "processed" / "prices" / "TEST.csv").exists()


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


def test_pipeline_integrates_macro_news_and_conservative_shock_analysis(
    tmp_path: Path,
) -> None:
    write_configuration(tmp_path)
    (tmp_path / "universe.yaml").write_text(
        """
version: 1
filters: {}
securities:
  - ticker: TEST
    cik: "1"
    company: Synthetic Test Fixture Only
    country: United States
    sector: Synthetic Sector
    currency: USD
""",
        encoding="utf-8",
    )
    (tmp_path / "macro.yaml").write_text(
        """
version: 1
series:
  synthetic_macro:
    series_id: SYNTH
    name: Synthetic Macro Series
""",
        encoding="utf-8",
    )
    (tmp_path / "exposures.yaml").write_text(
        """
version: 1
sector_exposures: {}
security_exposures:
  TEST:
    - series_key: synthetic_macro
      coefficient: -1.0
      rationale: Synthetic integration-test sensitivity only.
      assumption_date: 2025-01-01
      source: synthetic integration-test assumption
""",
        encoding="utf-8",
    )
    (tmp_path / "taxonomy.yaml").write_text(
        """
version: 1
categories:
  OPERATIONAL: [outage, disruption]
temporary_terms: [temporary]
resolution_terms: [resolved, restarted, restored]
damage_terms: []
structural_terms: []
severe_structural_terms: []
""",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path / "settings.yaml")
    settings.macro.enabled = True
    settings.news.enabled = True
    settings.shock.enabled = True
    settings.paths.macro = tmp_path / "macro.yaml"
    settings.paths.macro_exposures = tmp_path / "exposures.yaml"
    settings.paths.shock_taxonomy = tmp_path / "taxonomy.yaml"
    output = run_pipeline(
        settings,
        price_source=FakePriceSource(),
        fundamental_source=FakeFundamentalSource(),
        macro_source=FakeMacroSource(),
        news_source=FakeNewsSource(),
        fundamentals_as_of="2025-03-01T23:00:00Z",
    )
    result = output.results[0]
    assert result.shock_category == ShockCategory.OPERATIONAL
    assert result.shock_nature == ShockNature.PROBABLY_TEMPORARY
    assert result.temporary_shock_score is not None
    assert result.shock_independent_source_count == 2
    assert output.macro_analysis["synthetic_macro"].latest_value == 110.0
    assert len(output.macro_exported_files) == 2
    assert len(output.shock_exported_files) == 3
