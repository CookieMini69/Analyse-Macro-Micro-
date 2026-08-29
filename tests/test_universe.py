from pathlib import Path

import pytest

from src.screening.universe import UniverseError, auxiliary_benchmarks, load_universe


def test_loads_yaml_and_csv_then_applies_filters(tmp_path: Path) -> None:
    (tmp_path / "securities.csv").write_text(
        "ticker,company,country,sector,market_cap,market_cap_currency,market_cap_source,market_cap_source_url,market_cap_observation_date,market_cap_retrieved_at,market_cap_confidence\n"
        "AAA,Alpha,France,Industrials,2000000,EUR,Test Source,https://example.invalid/a,2026-01-01,2026-01-02T00:00:00Z,1.0\n"
        "BBB,Beta,Canada,Technology,3000000,CAD,Test Source,https://example.invalid/b,2026-01-01,2026-01-02T00:00:00Z,1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "universe.yaml").write_text(
        """
version: 1
csv_path: securities.csv
filters:
  minimum_market_cap: 1000000
  allowed_countries: [France]
securities: []
""",
        encoding="utf-8",
    )
    securities = load_universe(tmp_path / "universe.yaml")
    assert [security.ticker for security in securities] == ["AAA"]


def test_duplicate_ticker_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "universe.yaml"
    path.write_text(
        """
version: 1
filters: {}
securities:
  - {ticker: AAA}
  - {ticker: aaa}
""",
        encoding="utf-8",
    )
    with pytest.raises(UniverseError, match="duplicate ticker"):
        load_universe(path)


def test_auxiliary_benchmarks_are_unique() -> None:
    from src.models import Security

    securities = [
        Security(ticker="AAA", benchmark="WORLD", sector_benchmark="INDUSTRY"),
        Security(ticker="BBB", benchmark="WORLD", sector_benchmark="INDUSTRY"),
    ]
    assert {item.ticker for item in auxiliary_benchmarks(securities)} == {"WORLD", "INDUSTRY"}


def test_default_universe_has_global_sec_reporting_coverage() -> None:
    universe = load_universe(Path("config/universe.yaml"))
    countries = {security.country for security in universe}
    assert len(universe) >= 40
    assert {"United States", "France", "Japan", "Brazil", "South Africa"} <= countries
    assert all(security.cik for security in universe)
    assert all(security.currency == "USD" for security in universe)
