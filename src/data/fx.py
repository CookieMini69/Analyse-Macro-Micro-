"""Dated ECB reference FX rates through the free Frankfurter API."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import requests

from src.data.fundamentals import normalize_as_of
from src.data.http_json import CachedJsonClient
from src.models import DataQuality, DataStatus, FxRateObservation, FxRateResult

FRANKFURTER_V1 = "https://api.frankfurter.dev/v1"


class FrankfurterFxSource:
    def __init__(
        self,
        cache_dir: str | Path,
        *,
        cache_ttl_hours: int = 24,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.client = CachedJsonClient(
            Path(cache_dir) / "fx",
            user_agent="AI Stock Opportunity Scanner/1.0",
            cache_ttl_hours=cache_ttl_hours,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            session=session,
        )

    def fetch(self, base: str, quote: str, *, as_of=None) -> FxRateResult:
        cutoff = normalize_as_of(as_of)
        base, quote = base.upper(), quote.upper()
        pair = f"{base}/{quote}"
        endpoint = f"{FRANKFURTER_V1}/{cutoff.date().isoformat()}"
        url = f"{endpoint}?base={base}&symbols={quote}"
        retrieved = datetime.now(UTC)
        if base == quote:
            observation = FxRateObservation(
                base_currency=base,
                quote_currency=quote,
                rate=1.0,
                observation_date=cutoff.date(),
                as_of=cutoff,
                source="currency identity",
                source_url=url,
                retrieved_at=retrieved,
                unit=f"{quote} per {base}",
                confidence=1.0,
            )
            return FxRateResult(
                pair=pair, base_currency=base, quote_currency=quote, as_of=cutoff,
                status=DataStatus.AVAILABLE, data_quality=DataQuality.HIGH,
                observation=observation, retrieved_at=retrieved, source_url=url,
            )
        try:
            response = self.client.get_json(
                endpoint,
                params={"base": base, "symbols": quote},
                public_source_url=url,
                cache_namespace=f"fx_{base}_{quote}",
            )
            payload = response.payload
            retrieved = response.retrieved_at
            observation_date = datetime.fromisoformat(str(payload["date"])).date()
            rate = float(payload["rates"][quote])
            observation = FxRateObservation(
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                observation_date=observation_date,
                as_of=cutoff,
                source="ECB reference rates via Frankfurter",
                source_url=url,
                retrieved_at=retrieved,
                unit=f"{quote} per {base}",
            )
            return FxRateResult(
                pair=pair, base_currency=base, quote_currency=quote, as_of=cutoff,
                status=DataStatus.AVAILABLE, data_quality=DataQuality.MEDIUM,
                observation=observation, retrieved_at=retrieved, source_url=url,
                from_cache=response.from_cache,
            )
        except Exception as exc:
            return unavailable_fx_rate(base, quote, cutoff, url, str(exc))


def convert_currency(amount: float | None, result: FxRateResult) -> float | None:
    if amount is None or result.observation is None or result.status != DataStatus.AVAILABLE:
        return None
    return amount * result.observation.rate


def unavailable_fx_rate(
    base: str, quote: str, as_of: datetime, source_url: str, error: str
) -> FxRateResult:
    return FxRateResult(
        pair=f"{base}/{quote}", base_currency=base, quote_currency=quote,
        as_of=as_of, status=DataStatus.DATA_UNAVAILABLE,
        data_quality=DataQuality.UNAVAILABLE, retrieved_at=datetime.now(UTC),
        source_url=source_url, error=error,
    )


__all__ = ["FrankfurterFxSource", "convert_currency", "unavailable_fx_rate"]
