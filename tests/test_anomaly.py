from src.config import ScreeningSettings
from src.models import MetricValue
from src.screening.anomaly import candidate_reasons, decline_severity_score


def metrics(**overrides: float | None) -> dict[str, MetricValue]:
    values = {
        "drawdown_52w": -0.25,
        "drawdown_3m": -0.05,
        "drawdown_6m": -0.10,
        "relative_sector_performance": None,
    }
    values.update(overrides)
    return {
        key: MetricValue.available(value) if value is not None else MetricValue.unavailable("missing")
        for key, value in values.items()
    }


def test_candidate_filter_records_threshold_reason() -> None:
    reasons = candidate_reasons(metrics(), ScreeningSettings())
    assert len(reasons) == 1
    assert reasons[0].startswith("drawdown_52w")


def test_decline_score_does_not_impute_missing_component() -> None:
    missing_sector = decline_severity_score(metrics(relative_sector_performance=None))
    flat_sector = decline_severity_score(metrics(relative_sector_performance=0.0))
    assert missing_sector == flat_sector
    assert 0 < missing_sector < 100


def test_decline_score_is_capped_at_100() -> None:
    severe = metrics(
        drawdown_52w=-0.9,
        drawdown_3m=-0.9,
        drawdown_6m=-0.9,
        relative_sector_performance=-0.9,
    )
    assert decline_severity_score(severe) == 100.0

