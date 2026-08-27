from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.shock import analyze_shock
from src.macro_config import (
    MacroExposureDefinition,
    ShockTaxonomyConfig,
    load_shock_taxonomy,
)
from src.models import (
    DataQuality,
    DataStatus,
    MacroSeriesAnalysis,
    MetricValue,
    NewsArticle,
    NewsSearchResult,
    Security,
    ShockCategory,
    ShockNature,
)
from tests.test_fundamental_analysis import complete_data


def article(title: str, domain: str, minutes: int) -> NewsArticle:
    seen = datetime(2025, 3, 1, 12, tzinfo=UTC) - timedelta(minutes=minutes)
    return NewsArticle(
        title=title,
        url=f"https://{domain}/{minutes}",
        source_domain=domain,
        seen_at=seen,
        query='"Synthetic Test Company"',
        index_source_url="https://api.gdeltproject.org/synthetic-test-only",
        retrieved_at=datetime(2025, 3, 1, 13, tzinfo=UTC),
    )


def news_result(articles: list[NewsArticle]) -> NewsSearchResult:
    return NewsSearchResult(
        ticker="TEST",
        company="Synthetic Test Company",
        query='"Synthetic Test Company"',
        window_start=datetime(2025, 2, 1, tzinfo=UTC),
        as_of=datetime(2025, 3, 1, 23, tzinfo=UTC),
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        articles=articles,
        retrieved_at=datetime(2025, 3, 1, 13, tzinfo=UTC),
        source_url="https://api.gdeltproject.org/synthetic-test-only",
    )


def macro_analysis() -> MacroSeriesAnalysis:
    return MacroSeriesAnalysis(
        series_key="wti_oil",
        series_id="SYNTH-OIL",
        title="Synthetic Oil Series",
        as_of=datetime(2025, 3, 1, 23, tzinfo=UTC),
        latest_value=80.0,
        latest_observation_date=date(2025, 2, 28),
        unit="USD",
        frequency="Daily",
        changes={
            "absolute_30d": MetricValue.available(10.0),
            "percent_30d": MetricValue.available(10.0 / 70.0),
        },
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        source_url="https://fred.stlouisfed.org/series/SYNTH-OIL",
    )


def test_corroborated_resolution_is_only_probable_not_certain() -> None:
    taxonomy = load_shock_taxonomy("config/shock_taxonomy.yaml")
    security = Security(ticker="TEST", company="Synthetic Test Company")
    fundamental = analyze_fundamentals(complete_data())
    exposure = MacroExposureDefinition(
        series_key="wti_oil",
        coefficient=-1.0,
        rationale="Synthetic test exposure only.",
        assumption_date=date(2025, 1, 1),
        source="synthetic unit-test assumption",
    )
    result = analyze_shock(
        security,
        news_result(
            [
                article("Company outage resolved after temporary disruption", "one.test", 2),
                article("Company operations restarted and restored", "two.test", 1),
            ]
        ),
        {"wti_oil": macro_analysis()},
        [exposure],
        taxonomy,
        fundamental=fundamental,
        minimum_independent_sources=2,
        minimum_score_coverage=0.5,
    )
    assert result.category == ShockCategory.OPERATIONAL
    assert result.nature == ShockNature.PROBABLY_TEMPORARY
    assert result.nature != ShockNature.TEMPORARY
    assert result.independent_source_count == 2
    assert result.temporary_score.status == DataStatus.AVAILABLE
    assert result.macro_associations[0].aligned_with_headwind is True
    assert "not proof of causality" in result.macro_associations[0].interpretation


def test_severe_structural_language_takes_precedence() -> None:
    taxonomy = load_shock_taxonomy("config/shock_taxonomy.yaml")
    result = analyze_shock(
        Security(ticker="TEST", company="Synthetic Test Company"),
        news_result([article("Company bankruptcy follows debt default", "one.test", 1)]),
        {},
        [],
        taxonomy,
        fundamental=None,
    )
    assert result.nature == ShockNature.SEVERE_STRUCTURAL
    assert result.temporary_score.score is not None
    assert result.temporary_score.components["structural_damage"].score == 0.0


def test_no_matching_evidence_keeps_unknown_and_score_null() -> None:
    taxonomy = load_shock_taxonomy("config/shock_taxonomy.yaml")
    result = analyze_shock(
        Security(ticker="TEST", company="Synthetic Test Company"),
        news_result([article("Company holds annual community meeting", "one.test", 1)]),
        {},
        [],
        taxonomy,
        fundamental=None,
    )
    assert result.category == ShockCategory.UNKNOWN
    assert result.nature == ShockNature.UNCERTAIN
    assert result.temporary_score.score is None
    assert result.data_quality == DataQuality.LOW


def test_future_exposure_assumption_is_rejected() -> None:
    taxonomy = load_shock_taxonomy("config/shock_taxonomy.yaml")
    exposure = MacroExposureDefinition(
        series_key="wti_oil",
        coefficient=-1.0,
        rationale="Synthetic future assumption.",
        assumption_date=date(2025, 3, 2),
        source="synthetic unit-test assumption",
    )
    result = analyze_shock(
        Security(ticker="TEST", company="Synthetic Test Company"),
        news_result([article("Temporary operational disruption", "one.test", 1)]),
        {"wti_oil": macro_analysis()},
        [exposure],
        taxonomy,
    )
    assert result.macro_associations[0].status == DataStatus.DATA_UNAVAILABLE
    assert "not available at the cutoff" in result.macro_associations[0].reason


def test_taxonomy_rejects_unknown_category_labels() -> None:
    with pytest.raises(ValidationError, match="unknown shock categories"):
        ShockTaxonomyConfig(categories={"NOT_IN_SPECIFICATION": ["test"]})
