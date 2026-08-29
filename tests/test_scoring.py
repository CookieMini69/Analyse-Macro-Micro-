from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.shock import analyze_shock
from src.analysis.valuation import analyze_valuation
from src.config import ScenarioSettings, ScoringSettings, ValuationSettings
from src.forecasting.scenarios import analyze_scenarios
from src.models import (
    DataQuality,
    DataStatus,
    HistoricalAnalogue,
    HistoricalAnalogueResult,
    HistoricalEpisode,
    MetricValue,
    ShockNature,
)
from src.reporting.scoring import persist_scoring_results, scoring_summary_frame
from src.scoring.opportunity import analyze_opportunity_score
from src.scoring.risk import score_risk_resilience
from tests.test_fundamental_analysis import complete_data
from tests.test_scenarios import priced_security
from tests.test_shock import article, news_result
from src.macro_config import load_shock_taxonomy


AS_OF = datetime(2025, 3, 1, 23, tzinfo=UTC)


def scoring_fixture():
    security, prices = priced_security(price=20.0)
    data = complete_data()
    data.security = security
    fundamental = analyze_fundamentals(data)
    valuation = analyze_valuation(
        security,
        fundamental,
        prices,
        None,
        ValuationSettings(historical_minimum_points=1, minimum_score_coverage=0.40),
    )
    scenario = analyze_scenarios(
        security,
        fundamental,
        valuation,
        20.0,
        settings=ScenarioSettings(minimum_history_points=2),
        as_of=AS_OF,
    )
    shock = analyze_shock(
        security,
        news_result(
            [
                article("Company outage resolved after temporary disruption", "one.test", 2),
                article("Company operations restarted and restored", "two.test", 1),
            ]
        ),
        {},
        [],
        load_shock_taxonomy("config/shock_taxonomy.yaml"),
        fundamental=fundamental,
    )
    prior = HistoricalEpisode(
        peak_date=date(2023, 1, 1),
        peak_price=100,
        trough_date=date(2023, 2, 1),
        trough_price=70,
        recovery_date=date(2023, 8, 1),
        maximum_drawdown=-0.30,
        decline_duration_days=31,
        recovery_duration_days=181,
        total_recovery_days=212,
        subsequent_returns={"return_12m": MetricValue.available(0.35)},
    )
    historical = HistoricalAnalogueResult(
        ticker=security.ticker,
        company=security.company,
        as_of=AS_OF,
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        analogues=[
            HistoricalAnalogue(
                episode=prior,
                similarity_score=80,
                similarity_coverage=0.75,
            )
        ],
        detected_completed_episode_count=1,
        best_similarity_score=80,
        source="synthetic price history",
        retrieved_at=AS_OF,
    )
    return security, fundamental, valuation, shock, historical, scenario


def test_phase8_preserves_subscores_and_never_calls_score_probability() -> None:
    security, fundamental, valuation, shock, historical, scenario = scoring_fixture()
    result = analyze_opportunity_score(
        security,
        fundamental,
        valuation,
        shock,
        historical,
        scenario,
        ScoringSettings(),
        as_of=AS_OF,
        volatility=0.30,
        beta=1.10,
    )
    assert result.status == DataStatus.AVAILABLE
    assert set(result.opportunity.components) == {
        "fundamental_quality", "valuation", "temporary_shock", "normalization",
        "catalyst", "future_growth", "risk_resilience",
    }
    assert sum(item.weight for item in result.opportunity.components.values()) == pytest.approx(1)
    assert result.opportunity.score is not None
    assert 0 < result.confidence_score <= result.opportunity.coverage * 100
    assert "not a probability" in result.opportunity.interpretation
    assert "probability" not in result.score_band.lower()


def test_missing_shock_and_catalyst_reduce_coverage_instead_of_being_imputed() -> None:
    security, fundamental, valuation, _, historical, scenario = scoring_fixture()
    result = analyze_opportunity_score(
        security,
        fundamental,
        valuation,
        None,
        historical,
        scenario,
        ScoringSettings(),
        as_of=AS_OF,
        volatility=0.30,
        beta=1.10,
    )
    assert result.temporary_shock.status == DataStatus.DATA_UNAVAILABLE
    assert result.catalyst.status == DataStatus.DATA_UNAVAILABLE
    assert result.opportunity.coverage < 1.0
    assert result.opportunity.score is not None
    assert result.opportunity.score < result.opportunity.observed_score


def test_risk_score_is_resilience_and_penalizes_structural_evidence() -> None:
    _, fundamental, _, shock, _, scenario = scoring_fixture()
    temporary = score_risk_resilience(
        fundamental, scenario, shock, volatility=0.30, beta=1.0, minimum_coverage=0.25
    )
    structural_shock = shock.model_copy(update={"nature": ShockNature.SEVERE_STRUCTURAL})
    structural = score_risk_resilience(
        fundamental, scenario, structural_shock,
        volatility=0.30, beta=1.0, minimum_coverage=0.25,
    )
    assert temporary.score is not None and structural.score is not None
    assert structural.score < temporary.score


def test_scoring_reporting_persists_full_audit(tmp_path) -> None:
    security, fundamental, valuation, shock, historical, scenario = scoring_fixture()
    result = analyze_opportunity_score(
        security, fundamental, valuation, shock, historical, scenario,
        ScoringSettings(), as_of=AS_OF, volatility=0.30, beta=1.10,
    )
    frame = scoring_summary_frame([result])
    paths = persist_scoring_results([result], tmp_path / "processed", tmp_path / "reports")
    assert len(frame) == 1
    assert frame.iloc[0]["opportunity_score"] == result.opportunity.score
    assert {path.suffix for path in paths} == {".json", ".csv"}


def test_scoring_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="must sum to 1.0"):
        ScoringSettings(risk_weight=0.20)


def test_future_stage_result_is_excluded_from_scoring_cutoff() -> None:
    security, fundamental, valuation, shock, historical, scenario = scoring_fixture()
    valuation = valuation.model_copy(
        update={"as_of": datetime(2025, 3, 2, tzinfo=UTC)}
    )
    result = analyze_opportunity_score(
        security, fundamental, valuation, shock, historical, scenario,
        ScoringSettings(), as_of=AS_OF, volatility=0.30, beta=1.10,
    )
    assert result.valuation.status == DataStatus.DATA_UNAVAILABLE
