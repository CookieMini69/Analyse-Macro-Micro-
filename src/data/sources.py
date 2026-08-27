"""Interfaces and result containers for replaceable market-data sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from src.models import DataQuality, DataStatus, Security

if TYPE_CHECKING:
    from src.data.fundamentals import FundamentalDataResult


@dataclass(slots=True)
class PriceHistoryResult:
    """A normalized price frame plus source-level status."""

    security: Security
    frame: pd.DataFrame
    status: DataStatus
    data_quality: DataQuality
    source: str
    source_url: str | None
    error: str | None = None
    from_cache: bool = False
    warnings: list[str] = field(default_factory=list)


class PriceSource(Protocol):
    """Contract implemented by every V1 price provider."""

    def fetch(self, security: Security, *, period: str = "max") -> PriceHistoryResult:
        """Return normalized daily OHLCV observations for one security."""


class FundamentalSource(Protocol):
    """Contract for point-in-time fundamental providers."""

    def fetch(
        self,
        security: Security,
        *,
        as_of: date | datetime | str | None = None,
    ) -> "FundamentalDataResult":
        """Return only facts publicly available by the requested cutoff."""
