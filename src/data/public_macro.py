"""Free official macro and market-sentiment sources.

The adapters deliberately preserve an explicit point-in-time cutoff. ECB
vintages use ``VALID_FROM``/``VALID_TO``. Cboe put/call data uses the dated
official daily-statistics page. CFTC COT observations use a conservative,
configurable publication lag because the public dataset contains the Tuesday
position date rather than a reliable release timestamp.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import requests

from src.data.fundamentals import normalize_as_of
from src.macro_config import MacroSeriesDefinition
from src.models import DataQuality, DataStatus, MacroObservation, MacroSeriesResult


class PublicMacroError(RuntimeError):
    """Raised when an official free source returns unusable data."""


@dataclass(frozen=True, slots=True)
class _TextResponse:
    text: str
    retrieved_at: datetime
    from_cache: bool


class _CachedTextClient:
    def __init__(
        self,
        cache_dir: str | Path,
        *,
        cache_ttl_hours: int,
        timeout_seconds: int,
        max_retries: int,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": "AI Stock Opportunity Scanner/1.0", "Accept": "*/*"}
        )

    def get(self, url: str, *, params: dict[str, object], namespace: str) -> _TextResponse:
        material = json.dumps({"url": url, "params": params}, sort_keys=True)
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{namespace}_{digest}.json"
        cached = self._read(path)
        if cached is not None:
            return cached
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url, params=params, timeout=self.timeout_seconds
                )
                response.raise_for_status()
                retrieved_at = datetime.now(UTC)
                result = _TextResponse(response.text, retrieved_at, False)
                wrapper = {
                    "retrieved_at": retrieved_at.isoformat(),
                    "text": response.text,
                }
                temporary = path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(wrapper, ensure_ascii=False), encoding="utf-8"
                )
                temporary.replace(path)
                return result
            except (requests.RequestException, OSError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 8))
        raise PublicMacroError(f"official source request failed: {last_error}")

    def _read(self, path: Path) -> _TextResponse | None:
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            retrieved_at = datetime.fromisoformat(wrapper["retrieved_at"])
            if retrieved_at.tzinfo is None:
                retrieved_at = retrieved_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - retrieved_at > self.cache_ttl:
                return None
            return _TextResponse(str(wrapper["text"]), retrieved_at, True)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None


class _OfficialSource:
    def __init__(
        self,
        cache_dir: str | Path,
        *,
        cache_ttl_hours: int = 24,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.client = _CachedTextClient(
            cache_dir,
            cache_ttl_hours=cache_ttl_hours,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            session=session,
        )


class EcbMacroSource(_OfficialSource):
    """ECB Data Portal SDMX adapter with revision-validity filtering."""

    BASE = "https://data-api.ecb.europa.eu/service/data"

    def fetch(
        self,
        series_key: str,
        definition: MacroSeriesDefinition,
        *,
        as_of: date | datetime | str | None = None,
        history_years: int = 2,
    ) -> MacroSeriesResult:
        cutoff = normalize_as_of(as_of)
        start = cutoff.date() - timedelta(days=366 * history_years)
        # ECB REST paths separate the dataflow from the SDMX key with a slash
        # (for example ``FM/D.U2.EUR...``), while configuration keeps the
        # canonical dotted series identifier.
        api_path = definition.series_id.replace(".", "/", 1)
        url = f"{self.BASE}/{api_path}"
        response = self.client.get(
            url,
            params={
                "startPeriod": start.isoformat(),
                "endPeriod": cutoff.date().isoformat(),
                "format": "csvdata",
                "includeHistory": "true",
            },
            namespace=f"ecb_{_safe(definition.series_id)}",
        )
        rows = list(csv.DictReader(StringIO(response.text)))
        observations: list[MacroObservation] = []
        for row in rows:
            try:
                observed = date.fromisoformat(row["TIME_PERIOD"])
                value = float(row["OBS_VALUE"])
                valid_from_dt = _parse_datetime(row.get("VALID_FROM"))
                valid_to_dt = _parse_datetime(row.get("VALID_TO"))
            except (KeyError, TypeError, ValueError):
                continue
            effective_from = valid_from_dt or datetime.combine(
                observed, datetime_time.max, tzinfo=UTC
            )
            effective_to = valid_to_dt or datetime.max.replace(tzinfo=UTC)
            valid_from = effective_from.date()
            valid_to = effective_to.date()
            if (
                observed > cutoff.date()
                or effective_from > cutoff
                or effective_to <= cutoff
            ):
                continue
            observations.append(
                MacroObservation(
                    series_key=series_key,
                    series_id=definition.series_id,
                    series_title=row.get("TITLE_COMPL") or row.get("TITLE") or definition.name,
                    value=value,
                    observation_date=observed,
                    realtime_start=valid_from,
                    realtime_end=valid_to,
                    as_of=cutoff,
                    frequency=row.get("FREQ"),
                    unit=row.get("UNIT"),
                    source="European Central Bank Data Portal",
                    source_url=url,
                    retrieved_at=response.retrieved_at,
                    confidence=1.0,
                )
            )
        return _result(
            series_key,
            definition,
            cutoff,
            observations,
            response.retrieved_at,
            url,
            response.from_cache,
            quality=DataQuality.HIGH,
            empty_error="ECB returned no revision valid at the cutoff",
        )


class CboePutCallSource(_OfficialSource):
    """Dated Cboe daily options put/call ratio adapter (available since 2019)."""

    URL = "https://www.cboe.com/markets/us/options/market-statistics/daily/"

    def fetch(
        self,
        series_key: str,
        definition: MacroSeriesDefinition,
        *,
        as_of: date | datetime | str | None = None,
        history_years: int = 2,
    ) -> MacroSeriesResult:
        del history_years  # the official page exposes one dated daily snapshot
        cutoff = normalize_as_of(as_of)
        ratio_name = definition.parameters.get("ratio_name", "TOTAL PUT/CALL RATIO")
        escaped_name = re.escape(ratio_name)
        observations: list[MacroObservation] = []
        response: _TextResponse | None = None
        # Weekend/holiday URLs render the chosen calendar date but no ratios.
        # Walk back at most one week to the latest actual trading-day snapshot.
        for days_back in range(8):
            requested = cutoff.date() - timedelta(days=days_back)
            response = self.client.get(
                self.URL,
                params={"dt": requested.isoformat()},
                namespace=f"cboe_put_call_{requested.isoformat()}",
            )
            selected = _first_match(
                response.text,
                (r'"selectedDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
                 r'selectedDate\\"\s*:\\"(\d{4}-\d{2}-\d{2})'),
            )
            raw_value = _first_match(
                response.text,
                (
                    rf'{escaped_name}</td><td[^>]*>([0-9.]+)</td>',
                    rf'\\"name\\":\\"{escaped_name}\\",\\"value\\":\\"([0-9.]+)',
                ),
            )
            if selected and raw_value:
                observed = date.fromisoformat(selected)
                conservatively_available_at = datetime.combine(
                    observed, datetime_time.max, tzinfo=UTC
                )
                if conservatively_available_at <= cutoff:
                    observations.append(
                        MacroObservation(
                            series_key=series_key,
                            series_id=definition.series_id,
                            series_title=definition.name,
                            value=float(raw_value),
                            observation_date=observed,
                            realtime_start=observed,
                            realtime_end=date.max,
                            as_of=cutoff,
                            frequency="Daily",
                            unit="Ratio",
                            source="Cboe Daily Market Statistics",
                            source_url=f"{self.URL}?dt={observed.isoformat()}",
                            retrieved_at=response.retrieved_at,
                            confidence=0.95,
                        )
                    )
                    break
        assert response is not None
        return _result(
            series_key,
            definition,
            cutoff,
            observations,
            response.retrieved_at,
            self.URL,
            response.from_cache,
            quality=DataQuality.MEDIUM,
            empty_error="Cboe returned no dated put/call ratio at the cutoff",
        )


class CftcCotSource(_OfficialSource):
    """CFTC Public Reporting Environment adapter for COT positioning."""

    BASE = "https://publicreporting.cftc.gov/resource"

    def fetch(
        self,
        series_key: str,
        definition: MacroSeriesDefinition,
        *,
        as_of: date | datetime | str | None = None,
        history_years: int = 2,
    ) -> MacroSeriesResult:
        cutoff = normalize_as_of(as_of)
        parameters = definition.parameters
        market = parameters.get("market_name")
        if not market:
            raise PublicMacroError("cftc_cot requires parameters.market_name")
        lag = int(parameters.get("publication_lag_days", "7"))
        eligible_report_date = cutoff.date() - timedelta(days=lag)
        start = cutoff.date() - timedelta(days=366 * history_years + lag)
        url = f"{self.BASE}/{definition.series_id}.json"
        safe_market = market.replace("'", "''")
        response = self.client.get(
            url,
            params={
                "$where": (
                    f"market_and_exchange_names='{safe_market}' AND "
                    f"report_date_as_yyyy_mm_dd between '{start.isoformat()}T00:00:00.000' "
                    f"and '{eligible_report_date.isoformat()}T23:59:59.999'"
                ),
                "$order": "report_date_as_yyyy_mm_dd asc",
                "$limit": 5000,
            },
            namespace=f"cftc_{definition.series_id}_{_safe(market)}",
        )
        try:
            rows = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise PublicMacroError("CFTC returned invalid JSON") from exc
        if not isinstance(rows, list):
            raise PublicMacroError("CFTC returned a non-list payload")
        long_field = parameters.get("long_field", "lev_money_positions_long")
        short_field = parameters.get("short_field", "lev_money_positions_short")
        oi_field = parameters.get("open_interest_field", "open_interest_all")
        metric = parameters.get("metric", "net_pct_open_interest")
        observations: list[MacroObservation] = []
        for row in rows:
            try:
                observed = date.fromisoformat(str(row["report_date_as_yyyy_mm_dd"])[:10])
                long_value = float(row[long_field])
                short_value = float(row[short_field])
                if metric == "net_contracts":
                    value = long_value - short_value
                    unit = "Contracts"
                else:
                    open_interest = float(row[oi_field])
                    if open_interest <= 0:
                        continue
                    value = 100.0 * (long_value - short_value) / open_interest
                    unit = "Percent of open interest"
            except (KeyError, TypeError, ValueError):
                continue
            available = observed + timedelta(days=lag)
            available_at = datetime.combine(
                available, datetime_time.max, tzinfo=UTC
            )
            if available_at > cutoff:
                continue
            observations.append(
                MacroObservation(
                    series_key=series_key,
                    series_id=definition.series_id,
                    series_title=definition.name,
                    value=value,
                    observation_date=observed,
                    realtime_start=available,
                    realtime_end=date.max,
                    as_of=cutoff,
                    frequency="Weekly",
                    unit=unit,
                    source="U.S. Commodity Futures Trading Commission COT",
                    source_url=f"https://publicreporting.cftc.gov/stories/s/r4w3-av2u",
                    retrieved_at=response.retrieved_at,
                    confidence=0.90,
                )
            )
        return _result(
            series_key,
            definition,
            cutoff,
            observations,
            response.retrieved_at,
            f"https://publicreporting.cftc.gov/stories/s/r4w3-av2u",
            response.from_cache,
            quality=DataQuality.MEDIUM,
            empty_error="CFTC returned no conservatively available COT observations",
        )


def _result(
    key: str,
    definition: MacroSeriesDefinition,
    cutoff: datetime,
    observations: list[MacroObservation],
    retrieved_at: datetime,
    source_url: str,
    from_cache: bool,
    *,
    quality: DataQuality,
    empty_error: str,
) -> MacroSeriesResult:
    observations.sort(key=lambda item: item.observation_date)
    return MacroSeriesResult(
        series_key=key,
        series_id=definition.series_id,
        configured_name=definition.name,
        as_of=cutoff,
        status=DataStatus.AVAILABLE if observations else DataStatus.DATA_UNAVAILABLE,
        data_quality=quality if observations else DataQuality.UNAVAILABLE,
        observations=observations,
        retrieved_at=retrieved_at,
        source_url=source_url,
        from_cache=from_cache,
        error=None if observations else empty_error,
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _first_match(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)
