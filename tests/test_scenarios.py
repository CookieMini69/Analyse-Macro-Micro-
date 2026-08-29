from datetime import UTC, date, datetime

import pytest

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.valuation import analyze_valuation
from src.config import ScenarioSettings, ValuationSettings
from src.forecasting.scenarios import analyze_scenarios
from src.models import DataStatus
from src.reporting.scenarios import persist_scenario_results, scenario_summary_frame
from tests.test_fundamental_analysis import complete_data
from tests.test_valuation import priced_security, valuation_config


def scenario_fixture(*, with_dcf: bool = False):
    security, prices = priced_security(price=20.0)
    data = complete_data()
    data.security = security
    fundamental = analyze_fundamentals(data)
    valuation = analyze_valuation(
        security,
        fundamental,
        prices,
        valuation_config() if with_dcf else None,
        ValuationSettings(historical_minimum_points=1),
    )
    result = analyze_scenarios(
        security,
        fundamental,
        valuation,
        20.0,
        ScenarioSettings(minimum_history_points=2),
        as_of=datetime(2025, 3, 1, tzinfo=UTC),
    )
    return result


def test_scenarios_are_derived_from_observed_quartiles_and_median() -> None:
    result = scenario_fixture()

    assert result.status == DataStatus.AVAILABLE
    assert set(result.cases) == {"bear", "base", "bull"}
    assert [item.months for item in result.cases["base"].horizons] == [3, 6, 12, 18, 24]
    assert result.cases["bear"].statistic == "lower_quartile"
    assert result.cases["base"].statistic == "median"
    assert result.cases["bull"].statistic == "upper_quartile"
    assert result.targets.bear_target.value < result.targets.base_target.value
    assert result.targets.base_target.value < result.targets.bull_target.value
    assert result.targets.tp1.value < result.targets.tp2.value < result.targets.tp3.value
    assert result.cases["base"].assumptions["revenue_growth"].observation_count == 2
    assert result.cases["base"].assumptions["eps"].value is not None
    assert result.cases["base"].assumptions["free_cash_flow"].value is not None
    assert result.cases["base"].assumptions["wacc"].status == DataStatus.DATA_UNAVAILABLE
    assert result.cases["base"].assumption_coverage == pytest.approx(5 / 7, abs=1e-4)
    assert result.targets.normalized_fair_value.status == DataStatus.DATA_UNAVAILABLE


def test_targets_and_risk_reward_come_from_model_values() -> None:
    result = scenario_fixture()
    base_case = result.cases["base"]
    target_horizon = next(item for item in base_case.horizons if item.months == 12)
    available_model_values = sorted(
        metric.value
        for metric in target_horizon.model_values.values()
        if metric.value is not None
    )

    assert len(available_model_values) == 3
    assert result.targets.base_target.value == pytest.approx(available_model_values[1])
    assert result.risk_reward.upside_base.value == pytest.approx(
        result.targets.base_target.value / 20.0 - 1
    )
    assert result.risk_reward.downside_bear.value > 0
    assert result.risk_reward.risk_reward.status == DataStatus.DATA_UNAVAILABLE


def test_sourced_dcf_supplies_wacc_terminal_growth_and_fair_values() -> None:
    result = scenario_fixture(with_dcf=True)

    assert result.cases["base"].assumptions["wacc"].value == 0.10
    assert result.cases["base"].assumptions["terminal_growth"].value == 0.0
    assert result.targets.fair_value.value is not None
    assert result.targets.normalized_fair_value.value is not None
    assert result.targets.fair_value.value != result.targets.base_target.value


def test_future_dcf_assumptions_never_enter_scenarios() -> None:
    security, prices = priced_security(price=20.0)
    data = complete_data()
    data.security = security
    fundamental = analyze_fundamentals(data)
    valuation = analyze_valuation(
        security,
        fundamental,
        prices,
        valuation_config(assumption_date=date(2025, 3, 2)),
        ValuationSettings(historical_minimum_points=1),
    )
    result = analyze_scenarios(
        security,
        fundamental,
        valuation,
        20.0,
        ScenarioSettings(minimum_history_points=2),
        as_of=datetime(2025, 3, 1, tzinfo=UTC),
    )
    assert result.cases["base"].assumptions["wacc"].status == DataStatus.DATA_UNAVAILABLE
    assert result.cases["base"].assumptions["terminal_growth"].value is None


def test_future_fundamental_result_is_rejected() -> None:
    security, prices = priced_security(price=20.0)
    data = complete_data()
    data.security = security
    fundamental = analyze_fundamentals(data).model_copy(
        update={"as_of": datetime(2025, 3, 2, tzinfo=UTC)}
    )
    valuation = analyze_valuation(
        security, fundamental, prices, None,
        ValuationSettings(historical_minimum_points=1),
    )
    result = analyze_scenarios(
        security, fundamental, valuation, 20.0,
        ScenarioSettings(minimum_history_points=2),
        as_of=datetime(2025, 3, 1, tzinfo=UTC),
    )
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert "postdates" in result.error


def test_no_historical_multiple_means_no_arbitrary_target() -> None:
    security, prices = priced_security(price=20.0)
    data = complete_data()
    data.security = security
    fundamental = analyze_fundamentals(data)
    valuation = analyze_valuation(
        security,
        fundamental,
        prices,
        None,
        ValuationSettings(historical_minimum_points=1),
    )
    valuation = valuation.model_copy(
        update={
            "multiples": {
                name: multiple.model_copy(update={"history": []})
                for name, multiple in valuation.multiples.items()
            }
        }
    )
    result = analyze_scenarios(
        security,
        fundamental,
        valuation,
        20.0,
        ScenarioSettings(minimum_history_points=2),
        as_of=datetime(2025, 3, 1, tzinfo=UTC),
    )
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.targets.base_target.value is None
    assert all(
        case.target_price.status == DataStatus.DATA_UNAVAILABLE
        for case in result.cases.values()
    )


def test_invalidation_levels_are_fundamental_and_audited() -> None:
    result = scenario_fixture()
    levels = {item.metric: item for item in result.invalidation_levels}
    assert set(levels) == {
        "revenue_growth", "operating_margin", "fcf_margin", "net_debt_to_ebitda"
    }
    assert levels["revenue_growth"].operator == "<"
    assert levels["net_debt_to_ebitda"].operator == ">"
    assert levels["revenue_growth"].source_accessions
    assert "market_share" in result.missing_invalidation_dimensions


def test_scenario_reporting_writes_json_and_all_fifteen_case_horizons(tmp_path) -> None:
    result = scenario_fixture()
    frame = scenario_summary_frame([result])
    paths = persist_scenario_results([result], tmp_path / "processed", tmp_path / "reports")
    assert len(frame) == 15
    assert set(frame["scenario"]) == {"bear", "base", "bull"}
    assert {path.suffix for path in paths} == {".json", ".csv"}
