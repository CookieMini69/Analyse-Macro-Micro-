from datetime import UTC, datetime, timedelta

import pytest

from src.analysis.macro import analyze_macro_series
from src.data.macro import FredMacroError, FredMacroSource
from src.data.news import GdeltNewsSource
from src.macro_config import MacroSeriesDefinition
from src.models import DataStatus, Security


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params: dict, timeout: int) -> FakeResponse:
        self.calls.append((url, params))
        return FakeResponse(self.responses.pop(0))


def test_fred_uses_real_time_cutoff_and_never_persists_api_key(tmp_path) -> None:
    metadata = {
        "seriess": [
            {
                "id": "SYNTH",
                "title": "Synthetic Macro Series",
                "frequency": "Annual",
                "units": "Index",
                "seasonal_adjustment": "Not Seasonally Adjusted",
            }
        ]
    }
    observations = {
        "observations": [
            {
                "date": "2024-02-29",
                "value": "100",
                "realtime_start": "2025-03-01",
                "realtime_end": "9999-12-31",
            },
            {
                "date": "2025-02-28",
                "value": "120",
                "realtime_start": "2025-03-01",
                "realtime_end": "9999-12-31",
            },
            {
                "date": "2025-03-02",
                "value": "999",
                "realtime_start": "2025-03-01",
                "realtime_end": "9999-12-31",
            },
        ]
    }
    session = FakeSession([metadata, observations])
    api_key = "a" * 32
    source = FredMacroSource(
        tmp_path,
        api_key=api_key,
        max_retries=0,
        session=session,
    )
    definition = MacroSeriesDefinition(series_id="SYNTH", name="Synthetic")
    result = source.fetch(
        "synthetic",
        definition,
        as_of="2025-03-01T23:59:59Z",
        history_years=2,
    )
    assert result.status == DataStatus.AVAILABLE
    assert [item.value for item in result.observations] == [100.0, 120.0]
    assert all(item.observation_date <= result.as_of.date() for item in result.observations)
    assert all(call[1]["realtime_start"] == "2025-03-01" for call in session.calls)
    assert api_key not in result.source_url
    assert all(api_key not in path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json"))

    cached = source.fetch(
        "synthetic",
        definition,
        as_of="2025-03-01T23:59:59Z",
        history_years=2,
    )
    assert cached.from_cache is True
    assert len(session.calls) == 2

    analysis = analyze_macro_series(result)
    assert analysis.latest_value == 120.0
    assert analysis.changes["absolute_365d"].value == pytest.approx(20.0)
    assert analysis.changes["percent_365d"].value == pytest.approx(0.20)


def test_fred_rejects_placeholder_or_malformed_keys(tmp_path) -> None:
    with pytest.raises(FredMacroError):
        FredMacroSource(tmp_path, api_key="demo")


def test_gdelt_keeps_only_cutoff_filtered_public_metadata(tmp_path) -> None:
    cutoff = datetime.now(UTC).replace(microsecond=0)
    seen = cutoff - timedelta(days=1)
    future = cutoff + timedelta(minutes=1)
    payload = {
        "articles": [
            {
                "title": "Synthetic company outage resolved",
                "url": "https://news.example.test/article-1",
                "domain": "news.example.test",
                "seendate": seen.strftime("%Y%m%dT%H%M%SZ"),
                "language": "English",
                "sourcecountry": "United States",
                "body": "This field must never be stored.",
            },
            {
                "title": "Future synthetic article",
                "url": "https://news.example.test/future",
                "seendate": future.strftime("%Y%m%dT%H%M%SZ"),
            },
            {
                "title": "Duplicate URL",
                "url": "https://news.example.test/article-1",
                "domain": "news.example.test",
                "seendate": seen.strftime("%Y%m%dT%H%M%SZ"),
            },
        ]
    }
    session = FakeSession([payload])
    source = GdeltNewsSource(tmp_path, max_retries=0, session=session)
    result = source.fetch(
        Security(ticker="TEST", company="Synthetic Test Company"),
        as_of=cutoff,
        lookback_days=30,
        max_articles=75,
    )
    assert result.status == DataStatus.AVAILABLE
    assert len(result.articles) == 1
    serialized = result.model_dump_json()
    assert "This field must never be stored" not in serialized
    assert result.articles[0].seen_at <= cutoff


def test_gdelt_historical_limit_is_explicit_without_network_call(tmp_path) -> None:
    session = FakeSession([])
    source = GdeltNewsSource(tmp_path, max_retries=0, session=session)
    result = source.fetch(
        Security(ticker="TEST", company="Synthetic Test Company"),
        as_of=datetime.now(UTC) - timedelta(days=100),
    )
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert "three-month" in result.error
    assert session.calls == []
