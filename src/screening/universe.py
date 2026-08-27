"""Configurable YAML/CSV security universe loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.models import Security


class UniverseFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_market_cap: float | None = Field(default=None, ge=0)
    allowed_countries: list[str] = Field(default_factory=list)


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    csv_path: Path | None = None
    filters: UniverseFilters = Field(default_factory=UniverseFilters)
    securities: list[Security] = Field(default_factory=list)


class UniverseError(ValueError):
    """Raised when a configured universe is malformed or unusable."""


def _empty_to_none(value: Any) -> Any:
    if pd.isna(value) or (isinstance(value, str) and not value.strip()):
        return None
    return value


def _load_csv(path: Path) -> list[Security]:
    if not path.exists():
        raise UniverseError(f"universe CSV does not exist: {path}")
    frame = pd.read_csv(path)
    if "ticker" not in frame.columns:
        raise UniverseError("universe CSV must contain a 'ticker' column")
    supported_fields = set(Security.model_fields)
    unknown_fields = set(frame.columns) - supported_fields
    if unknown_fields:
        raise UniverseError(
            "unsupported universe CSV columns: " + ", ".join(sorted(unknown_fields))
        )
    records = []
    for row in frame.to_dict(orient="records"):
        cleaned = {key: _empty_to_none(value) for key, value in row.items()}
        records.append(Security.model_validate(cleaned))
    return records


def _apply_filters(securities: list[Security], filters: UniverseFilters) -> list[Security]:
    allowed = {country.casefold() for country in filters.allowed_countries}
    selected: list[Security] = []
    for security in securities:
        if allowed and security.country and security.country.casefold() not in allowed:
            continue
        if filters.minimum_market_cap is not None:
            if security.market_cap is None or security.market_cap < filters.minimum_market_cap:
                continue
        selected.append(security)
    return selected


def load_universe(path: str | Path) -> list[Security]:
    """Load, merge, deduplicate, and filter an explicit point-in-time universe."""

    universe_path = Path(path).expanduser().resolve()
    with universe_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    config = UniverseConfig.model_validate(raw)

    securities = list(config.securities)
    if config.csv_path is not None:
        csv_path = (
            config.csv_path
            if config.csv_path.is_absolute()
            else (universe_path.parent / config.csv_path).resolve()
        )
        securities.extend(_load_csv(csv_path))

    deduplicated: dict[str, Security] = {}
    for security in securities:
        key = security.ticker.upper()
        if key in deduplicated:
            raise UniverseError(f"duplicate ticker in universe: {security.ticker}")
        deduplicated[key] = security
    return _apply_filters(list(deduplicated.values()), config.filters)


def auxiliary_benchmarks(securities: list[Security]) -> list[Security]:
    """Return unique benchmark tickers required for relative metrics."""

    primary = {security.ticker.upper() for security in securities}
    requested: dict[str, Security] = {}
    for security in securities:
        for ticker in (security.benchmark, security.sector_benchmark):
            if ticker and ticker.upper() not in primary:
                requested.setdefault(
                    ticker.upper(),
                    Security(ticker=ticker, company=f"Benchmark {ticker}"),
                )
    return list(requested.values())

