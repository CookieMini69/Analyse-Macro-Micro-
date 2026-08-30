import json
from datetime import UTC, datetime, timedelta

import pytest
import requests

from src.analysis.macro import analyze_macro_series
from src.data.macro import FredMacroError, FredMacroSource
from src.data.http_json import CachedJsonClient, ExternalDataError
from src.data.news import GdeltNewsSource
from src.data.public_macro import CboePutCallSource, CftcCotSource, EcbMacroSource
from src.macro_config import MacroSeriesDefinition
from src.models import DataStatus, MacroObservation, Security


class FakeResponse:
    def __init__(self, payload: dict | None = None, *, text: str | None = None) -> None:
        self.payload = payload
        self.text = text if text is not None else ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, responses: list[dict | str]) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params: dict, timeout: int) -> FakeResponse:
        self.calls.append((url, params))
        response = self.responses.pop(0)
        return FakeResponse(response if isinstance(response, dict) else None, text=response if isinstance(response, str) else None)


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
            {
                "date": "2024-12-31",
                "value": "888",
                "realtime_start": "2025-03-02",
                "realtime_end": "9999-12-31",
            },
            {
                "date": "2024-12-30",
                "value": "777",
                "realtime_start": "2024-01-01",
                "realtime_end": "2025-02-28",
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


def test_fred_uses_st_louis_date_around_european_midnight(tmp_path) -> None:
    session = FakeSession([
        {"seriess": [{"id": "SYNTH", "title": "Synthetic"}]},
        {"observations": [{
            "date": "2025-02-28", "value": "1",
            "realtime_start": "2025-02-28", "realtime_end": "9999-12-31",
        }]},
    ])
    source = FredMacroSource(
        tmp_path, api_key="a" * 32, max_retries=0, session=session
    )
    result = source.fetch(
        "synthetic",
        MacroSeriesDefinition(series_id="SYNTH", name="Synthetic"),
        as_of="2025-03-01T00:30:00Z",
    )
    assert result.status == DataStatus.AVAILABLE
    assert all(call[1]["realtime_start"] == "2025-02-28" for call in session.calls)


def test_external_http_error_never_echoes_secret_query_params(tmp_path) -> None:
    secret = "s" * 32

    class RejectedResponse:
        status_code = 400
        url = f"https://api.example.invalid/data?api_key={secret}"

        def raise_for_status(self) -> None:
            raise requests.HTTPError(
                f"400 Client Error for url: {self.url}", response=self
            )

    class RejectedSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}
            self.calls = 0

        def get(self, url: str, *, params: dict, timeout: int):
            self.calls += 1
            return RejectedResponse()

    session = RejectedSession()
    client = CachedJsonClient(
        tmp_path, user_agent="test", cache_ttl_hours=1,
        timeout_seconds=1, max_retries=3, session=session,
    )
    with pytest.raises(ExternalDataError) as captured:
        client.get_json(
            "https://api.example.invalid/data",
            params={"api_key": secret},
            public_source_url="https://example.invalid/public",
            cache_namespace="test",
        )
    assert secret not in str(captured.value)
    assert "HTTP 400" in str(captured.value)
    assert session.calls == 1


def test_macro_model_rejects_a_vintage_unavailable_at_cutoff() -> None:
    with pytest.raises(ValueError, match="availability period"):
        MacroObservation(
            series_key="synthetic",
            series_id="SYNTH",
            series_title="Synthetic",
            value=1.0,
            observation_date=datetime(2024, 1, 1).date(),
            realtime_start=datetime(2025, 3, 2).date(),
            realtime_end=datetime(9999, 12, 31).date(),
            as_of=datetime(2025, 3, 1, tzinfo=UTC),
            source_url="https://fred.stlouisfed.org/series/SYNTH",
            retrieved_at=datetime(2025, 3, 1, tzinfo=UTC),
        )


def test_ecb_keeps_only_revision_valid_at_cutoff(tmp_path) -> None:
    csv_payload = """KEY,FREQ,TIME_PERIOD,OBS_VALUE,TITLE,UNIT,VALID_FROM,VALID_TO
X,D,2025-01-01,2.5,ECB test rate,PCPA,2025-01-01T01:00:00+01:00,2025-02-01T01:00:00+01:00
X,D,2025-01-01,2.0,ECB test rate,PCPA,2025-02-01T01:00:00+01:00,
X,D,2025-02-02,9.9,Future value,PCPA,2025-02-02T01:00:00+01:00,
"""
    source = EcbMacroSource(tmp_path, max_retries=0, session=FakeSession([csv_payload]))
    definition = MacroSeriesDefinition(
        provider="ecb", series_id="X", name="ECB test rate"
    )
    result = source.fetch("ecb_test", definition, as_of="2025-01-15")
    assert result.status == DataStatus.AVAILABLE
    assert [item.value for item in result.observations] == [2.5]
    assert result.observations[0].source == "European Central Bank Data Portal"


def test_cboe_put_call_preserves_selected_market_date(tmp_path) -> None:
    html = (
        '<script>{"selectedDate":"2025-01-03"}</script>'
        '<td>TOTAL PUT/CALL RATIO</td><td class="x">1.23</td>'
    )
    source = CboePutCallSource(tmp_path, max_retries=0, session=FakeSession([html]))
    definition = MacroSeriesDefinition(
        provider="cboe_put_call",
        series_id="TOTAL_PUT_CALL_RATIO",
        name="Cboe Total Put/Call Ratio",
        parameters={"ratio_name": "TOTAL PUT/CALL RATIO"},
    )
    result = source.fetch("put_call", definition, as_of="2025-01-05")
    assert result.status == DataStatus.AVAILABLE
    assert result.observations[0].observation_date.isoformat() == "2025-01-03"
    assert result.observations[0].value == 1.23


def test_cftc_cot_applies_conservative_publication_lag(tmp_path) -> None:
    rows = json.dumps(
        [
            {
                "report_date_as_yyyy_mm_dd": "2025-01-07T00:00:00.000",
                "lev_money_positions_long": "300",
                "lev_money_positions_short": "100",
                "open_interest_all": "1000",
            },
            {
                "report_date_as_yyyy_mm_dd": "2025-01-14T00:00:00.000",
                "lev_money_positions_long": "900",
                "lev_money_positions_short": "0",
                "open_interest_all": "1000",
            },
        ]
    )
    source = CftcCotSource(tmp_path, max_retries=0, session=FakeSession([rows]))
    definition = MacroSeriesDefinition(
        provider="cftc_cot",
        series_id="gpe5-46if",
        name="CFTC test",
        parameters={"market_name": "S&P 500 Consolidated", "publication_lag_days": "7"},
    )
    result = source.fetch("cftc_test", definition, as_of="2025-01-15")
    assert result.status == DataStatus.AVAILABLE
    assert [item.value for item in result.observations] == [20.0]
    assert result.observations[0].realtime_start.isoformat() == "2025-01-14"


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

