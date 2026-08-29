"""Yahoo Finance daily prices with normalized provenance and a local cache."""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import yfinance as yf

from src.data.sources import PriceHistoryResult
from src.models import DataQuality, DataStatus, Security

LOGGER = logging.getLogger(__name__)

PRICE_COLUMNS = [
    "ticker",
    "observation_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "exchange",
    "currency",
    "source",
    "source_url",
    "retrieved_at",
    "period",
    "unit",
    "confidence",
    "data_status",
]


def empty_price_frame() -> pd.DataFrame:
    """Return an empty frame with the stable public schema."""

    return pd.DataFrame(columns=PRICE_COLUMNS)


def _safe_cache_name(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ticker)


def validate_price_frame(frame: pd.DataFrame) -> list[str]:
    """Return validation problems without mutating or repairing source data."""

    problems: list[str] = []
    missing = [column for column in PRICE_COLUMNS if column not in frame.columns]
    if missing:
        problems.append(f"missing columns: {', '.join(missing)}")
        return problems
    if frame.empty:
        problems.append("no price observations")
        return problems
    dates = pd.to_datetime(frame["observation_date"], errors="coerce")
    if dates.isna().any():
        problems.append("one or more invalid observation dates")
    if dates.duplicated().any():
        problems.append("duplicate observation dates")
    for column in ("open", "high", "low", "close", "adjusted_close"):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if (numeric.dropna() <= 0).any():
            problems.append(f"{column} contains non-positive values")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    if (volume.dropna() < 0).any():
        problems.append("volume contains negative values")
    return problems


def assess_price_quality(frame: pd.DataFrame) -> DataQuality:
    """Assess one-source history; V1 never labels a single source as HIGH."""

    if frame.empty:
        return DataQuality.UNAVAILABLE
    usable = pd.to_numeric(frame.get("adjusted_close"), errors="coerce")
    if usable.isna().all():
        usable = pd.to_numeric(frame.get("close"), errors="coerce")
    completeness = float(usable.notna().mean()) if len(usable) else 0.0
    if len(frame) >= 252 and completeness >= 0.95:
        return DataQuality.MEDIUM
    if usable.notna().any():
        return DataQuality.LOW
    return DataQuality.UNAVAILABLE


class YahooFinancePriceSource:
    """Fetch unadjusted and adjusted daily bars from Yahoo via yfinance.

    Yahoo Finance is a convenient, free V1 source but is not an official exchange
    feed. Results therefore receive confidence below 1.0 and at most MEDIUM
    quality until corroboration is implemented in a later phase.
    """

    name = "Yahoo Finance via yfinance"

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        cache_ttl_hours: int = 18,
        confidence: float = 0.8,
    ) -> None:
        env_cache = os.getenv("STOCK_SCANNER_CACHE_DIR")
        self.cache_dir = Path(env_cache) if env_cache else Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.confidence = confidence

    def fetch(self, security: Security, *, period: str = "max") -> PriceHistoryResult:
        # The scaling rule is part of the normalized data contract. Including it
        # in the cache key prevents an old GBp-denominated London cache entry
        # from being mistaken for a GBP-denominated observation.
        cache_key = f"{security.ticker}__{period}__scale_{security.price_scale:g}"
        cache_path = self.cache_dir / f"{_safe_cache_name(cache_key)}.csv"
        cached = self._read_fresh_cache(cache_path)
        if cached is not None:
            return self._result(security, cached, from_cache=True)

        source_url = f"https://finance.yahoo.com/quote/{quote(security.ticker, safe='')}"
        try:
            history, metadata = self._download_history(security.ticker, period=period)
        except Exception as exc:  # provider/network exceptions are deliberately isolated
            LOGGER.error("Price download failed for %s: %s", security.ticker, exc)
            return PriceHistoryResult(
                security=security,
                frame=empty_price_frame(),
                status=DataStatus.DATA_UNAVAILABLE,
                data_quality=DataQuality.UNAVAILABLE,
                source=self.name,
                source_url=source_url,
                error=f"{type(exc).__name__}: {exc}",
            )

        if history.empty:
            return PriceHistoryResult(
                security=security,
                frame=empty_price_frame(),
                status=DataStatus.DATA_UNAVAILABLE,
                data_quality=DataQuality.UNAVAILABLE,
                source=self.name,
                source_url=source_url,
                error="data_unavailable: provider returned no observations",
            )

        normalized = self._normalize(history, metadata, security, source_url)
        problems = validate_price_frame(normalized)
        if problems:
            return PriceHistoryResult(
                security=security,
                frame=normalized,
                status=DataStatus.INVALID,
                data_quality=DataQuality.LOW,
                source=self.name,
                source_url=source_url,
                error="; ".join(problems),
                warnings=problems,
            )
        normalized.to_csv(cache_path, index=False)
        return self._result(security, normalized, from_cache=False)

    def _download_history(self, ticker: str, *, period: str) -> tuple[pd.DataFrame, dict[str, Any]]:
        instrument = yf.Ticker(ticker)
        history = instrument.history(
            period=period,
            interval="1d",
            auto_adjust=False,
            actions=False,
            repair=False,
            raise_errors=True,
        )
        metadata = getattr(instrument, "history_metadata", {}) or {}
        return history, metadata

    def _normalize(
        self,
        history: pd.DataFrame,
        metadata: dict[str, Any],
        security: Security,
        source_url: str,
    ) -> pd.DataFrame:
        retrieved_at = datetime.now(UTC).isoformat()
        index_dates = pd.to_datetime(history.index, errors="coerce")
        if getattr(index_dates, "tz", None) is not None:
            index_dates = index_dates.tz_localize(None)

        def source_column(name: str) -> pd.Series:
            if name in history.columns:
                values = pd.to_numeric(history[name], errors="coerce")
                if name != "Volume":
                    values = values * security.price_scale
                return values
            return pd.Series(pd.NA, index=history.index, dtype="Float64")

        normalized = pd.DataFrame(
            {
                "ticker": security.ticker,
                "observation_date": index_dates.date,
                "open": source_column("Open").to_numpy(),
                "high": source_column("High").to_numpy(),
                "low": source_column("Low").to_numpy(),
                "close": source_column("Close").to_numpy(),
                "adjusted_close": source_column("Adj Close").to_numpy(),
                "volume": source_column("Volume").to_numpy(),
                "exchange": security.exchange or metadata.get("exchangeName") or metadata.get("exchange"),
                "currency": security.currency or metadata.get("currency"),
                "source": self.name,
                "source_url": source_url,
                "retrieved_at": retrieved_at,
                "period": "1d",
                "unit": security.currency or metadata.get("currency"),
                "confidence": self.confidence,
            }
        )
        # Some long European Yahoo histories contain zero OHLC values around
        # old corporate actions while another price field remains valid. Zero
        # is not a price: preserve it as missing. Downstream selection can use
        # the explicitly disclosed close fallback when adjusted close is null.
        for price_column in ("open", "high", "low", "close", "adjusted_close"):
            invalid = pd.to_numeric(normalized[price_column], errors="coerce") <= 0
            normalized.loc[invalid, price_column] = pd.NA
        has_price = normalized["adjusted_close"].notna() | normalized["close"].notna()
        normalized["data_status"] = has_price.map(
            {True: DataStatus.AVAILABLE.value, False: DataStatus.DATA_UNAVAILABLE.value}
        )
        return normalized[PRICE_COLUMNS].sort_values("observation_date").reset_index(drop=True)

    def _read_fresh_cache(self, path: Path) -> pd.DataFrame | None:
        if not path.exists():
            return None
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if datetime.now(UTC) - modified_at > self.cache_ttl:
            return None
        try:
            frame = pd.read_csv(path, parse_dates=["observation_date", "retrieved_at"])
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            LOGGER.warning("Ignoring unreadable price cache %s: %s", path, exc)
            return None
        if validate_price_frame(frame):
            LOGGER.warning("Ignoring invalid price cache %s", path)
            return None
        return frame

    def _result(
        self, security: Security, frame: pd.DataFrame, *, from_cache: bool
    ) -> PriceHistoryResult:
        source_url = str(frame["source_url"].dropna().iloc[-1]) if frame["source_url"].notna().any() else None
        return PriceHistoryResult(
            security=security,
            frame=frame,
            status=DataStatus.AVAILABLE,
            data_quality=assess_price_quality(frame),
            source=self.name,
            source_url=source_url,
            from_cache=from_cache,
        )
