from datetime import UTC, date, datetime

import pytest

from src.alerts.engine import build_alerts, persist_local_alerts
from src.config import AlertSettings
from src.models import DataQuality, OpportunityCandidate, PeaEligibilityStatus


def _candidate(**updates: object) -> OpportunityCandidate:
    values = {
        "ticker": "TEST.PA",
        "company": "Test SA",
        "observation_date": date(2026, 8, 29),
        "pea_eligibility_status": PeaEligibilityStatus.REVIEW_REQUIRED,
        "opportunity_score": 72.0,
        "opportunity_score_coverage": 0.75,
        "drawdown_52w": -0.25,
        "decline_severity_score": 65.0,
        "is_candidate": True,
        "candidate_reasons": ["drawdown_52w"],
        "data_quality": DataQuality.MEDIUM,
        "retrieved_at": datetime(2026, 8, 30, tzinfo=UTC),
    }
    values.update(updates)
    return OpportunityCandidate.model_validate(values)


def test_alert_selection_is_score_coverage_and_pea_gated() -> None:
    settings = AlertSettings()
    alerts = build_alerts(
        [
            _candidate(),
            _candidate(ticker="LOW.PA", opportunity_score=49.9),
            _candidate(ticker="ADR", pea_eligibility_status=PeaEligibilityStatus.UNKNOWN),
            _candidate(ticker="MISSING.PA", opportunity_score=None),
        ],
        settings,
        generated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    assert [item.ticker for item in alerts] == ["TEST.PA"]
    assert alerts[0].alert_id == "cdda350bec0cb0d63507582a"


def test_local_alert_delivery_is_deduplicated(tmp_path) -> None:
    alerts = build_alerts(
        [_candidate()],
        AlertSettings(),
        generated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    first, files = persist_local_alerts(
        alerts, tmp_path / "alerts", tmp_path / "state.json"
    )
    second, second_files = persist_local_alerts(
        alerts, tmp_path / "alerts", tmp_path / "state.json"
    )
    assert len(first) == 1
    assert len(files) == 3
    assert all(path.exists() for path in files)
    assert second == []
    assert second_files == []


def test_corrupt_alert_state_fails_closed(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text("not json", encoding="utf-8")
    alerts = build_alerts([_candidate()], AlertSettings())
    with pytest.raises(ValueError, match="state is unreadable"):
        persist_local_alerts(alerts, tmp_path / "alerts", state)

