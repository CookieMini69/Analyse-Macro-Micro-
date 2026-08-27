"""Point-in-time macro histories from the official FRED/ALFRED API."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from src.data.http_json import CachedJsonClient
from src.data.fundamentals import normalize_as_of
from src.macro_config import MacroSeriesDefinition
from src.models import (
    DataQuality,
    DataStatus,
    MacroObservation,
    MacroSeriesResult,
)

FRED_API_BASE = "https://api.stlouisfed.org/fred"
FRED_API_KEY_PATTERN = re.compile(r"^[a-z0-9]{32}$")


class FredMacroError(RuntimeError):
    """Raised for invalid FRED configuration or payloads."""


def validate_fred_api_key(api_key: str) -> str:
    value = api_key.strip()
    if not FRED_API_KEY_PATTERN.fullmatch(value):
        raise FredMacroError(
            "FRED_API_KEY must be a registered 32-character lowercase alphanumeric key"
        )
    return value


class FredMacroSource:
    """Retrieve values known at ``as_of`` using ALFRED real-time periods."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        api_key: str,
        cache_ttl_hours: int = 24,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = validate_fred_api_key(api_key)
        self.client = CachedJsonClient(
            cache_dir,
            user_agent="AI Stock Opportunity Scanner/0.6",
            cache_ttl_hours=cache_ttl_hours,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            session=session,
        )

    def fetch(
        self,
        series_key: str,
        definition: MacroSeriesDefinition,
        *,
        as_of: date | datetime | str | None = None,
        history_years: int = 2,
    ) -> MacroSeriesResult:
        cutoff = normalize_as_of(as_of)
        cutoff_date = cutoff.date()
        series_url = (
            "https://fred.stlouisfed.org/series/"
            + quote(definition.series_id, safe="")
        )
        common = {
            "api_key": self.api_key,
            "file_type": "json",
            "series_id": definition.series_id,
            "realtime_start": cutoff_date.isoformat(),
            "realtime_end": cutoff_date.isoformat(),
        }
        try:
            metadata_response = self.client.get_json(
                f"{FRED_API_BASE}/series",
                params=common,
                public_source_url=series_url,
                cache_namespace=f"series_{definition.series_id}",
            )
            observation_start = cutoff_date - timedelta(days=366 * history_years)
            observations_response = self.client.get_json(
                f"{FRED_API_BASE}/series/observations",
                params={
                    **common,
                    "observation_start": observation_start.isoformat(),
                    "observation_end": cutoff_date.isoformat(),
                    "sort_order": "asc",
                },
                public_source_url=series_url,
                cache_namespace=f"observations_{definition.series_id}",
            )
            metadata_rows = metadata_response.payload.get("seriess", [])
            if not metadata_rows or not isinstance(metadata_rows[0], dict):
                raise FredMacroError(
                    f"series {definition.series_id} was unavailable at {cutoff_date}"
                )
            metadata = metadata_rows[0]
            observations = self._normalize_observations(
                series_key,
                definition,
                metadata,
                observations_response.payload,
                cutoff,
                series_url,
                observations_response.retrieved_at,
            )
            retrieved_at = max(
                metadata_response.retrieved_at, observations_response.retrieved_at
            )
            if not observations:
                return unavailable_macro_series(
                    series_key,
                    definition,
                    cutoff,
                    series_url,
                    "FRED returned no numeric observations valid at the cutoff",
                    retrieved_at=retrieved_at,
                )
            return MacroSeriesResult(
                series_key=series_key,
                series_id=definition.series_id,
                configured_name=definition.name,
                as_of=cutoff,
                status=DataStatus.AVAILABLE,
                data_quality=DataQuality.MEDIUM,
                observations=observations,
                retrieved_at=retrieved_at,
                source_url=series_url,
                from_cache=(
                    metadata_response.from_cache and observations_response.from_cache
                ),
            )
        except Exception as exc:
            return unavailable_macro_series(
                series_key,
                definition,
                cutoff,
                series_url,
                f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _normalize_observations(
        series_key: str,
        definition: MacroSeriesDefinition,
        metadata: dict,
        payload: dict,
        cutoff: datetime,
        source_url: str,
        retrieved_at: datetime,
    ) -> list[MacroObservation]:
        rows = payload.get("observations", [])
        observations: list[MacroObservation] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get("value") in {None, "."}:
                continue
            try:
                observation_date = date.fromisoformat(str(row["date"]))
                realtime_start = date.fromisoformat(str(row["realtime_start"]))
                realtime_end = date.fromisoformat(str(row["realtime_end"]))
                value = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if observation_date > cutoff.date():
                continue
            observations.append(
                MacroObservation(
                    series_key=series_key,
                    series_id=definition.series_id,
                    series_title=str(metadata.get("title") or definition.name),
                    value=value,
                    observation_date=observation_date,
                    realtime_start=realtime_start,
                    realtime_end=realtime_end,
                    as_of=cutoff,
                    frequency=metadata.get("frequency"),
                    unit=metadata.get("units"),
                    seasonal_adjustment=metadata.get("seasonal_adjustment"),
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                )
            )
        return sorted(observations, key=lambda item: item.observation_date)


def unavailable_macro_series(
    series_key: str,
    definition: MacroSeriesDefinition,
    as_of: datetime,
    source_url: str,
    error: str,
    *,
    retrieved_at: datetime | None = None,
) -> MacroSeriesResult:
    return MacroSeriesResult(
        series_key=series_key,
        series_id=definition.series_id,
        configured_name=definition.name,
        as_of=as_of,
        status=DataStatus.DATA_UNAVAILABLE,
        data_quality=DataQuality.UNAVAILABLE,
        observations=[],
        retrieved_at=retrieved_at or datetime.now(UTC),
        source_url=source_url,
        error=error,
    )
