from datetime import UTC, datetime

import pytest

from src.data.fx import FrankfurterFxSource, convert_currency
from src.models import DataStatus


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"amount": 1.0, "base": "USD", "date": "2025-02-28", "rates": {"EUR": 0.96}}


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params, timeout))
        return FakeResponse()


def test_fx_rate_is_dated_and_converts_without_replacing_original(tmp_path) -> None:
    session = FakeSession()
    source = FrankfurterFxSource(tmp_path, session=session, max_retries=0)
    result = source.fetch(
        "USD", "EUR", as_of=datetime(2025, 3, 1, 12, tzinfo=UTC)
    )
    assert result.status == DataStatus.AVAILABLE
    assert result.observation is not None
    assert result.observation.observation_date.isoformat() == "2025-02-28"
    assert result.observation.source == "ECB reference rates via Frankfurter"
    assert convert_currency(100.0, result) == pytest.approx(96.0)
    assert session.calls[0][1] == {"base": "USD", "symbols": "EUR"}


def test_fx_identity_needs_no_external_request(tmp_path) -> None:
    session = FakeSession()
    result = FrankfurterFxSource(tmp_path, session=session).fetch("EUR", "EUR")
    assert result.observation.rate == 1.0
    assert session.calls == []


def test_future_fx_observation_is_rejected_as_unavailable(tmp_path) -> None:
    class FutureResponse(FakeResponse):
        def json(self):
            return {"base": "USD", "date": "2025-03-02", "rates": {"EUR": 0.96}}

    class FutureSession(FakeSession):
        def get(self, url, *, params, timeout):
            return FutureResponse()

    result = FrankfurterFxSource(
        tmp_path, session=FutureSession(), max_retries=0
    ).fetch("USD", "EUR", as_of="2025-03-01")
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert "postdate" in result.error
