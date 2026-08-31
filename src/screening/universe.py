"""Configurable YAML/CSV security universe loading."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.models import PeaEligibilityStatus, Security


PEA_RULE_SOURCE_URL = (
    "https://www.amf-france.org/fr/espace-epargnants/comprendre-les-produits-financiers/"
    "supports-dinvestissement/pea-tout-savoir-sur-le-plan-depargne-en-actions"
)
PEA_RULE_CHECKED_AT = date(2026, 8, 30)
EEA_COUNTRIES = frozenset(
    {
        "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia",
        "Czech Republic", "Denmark", "Estonia", "Finland", "France", "Germany",
        "Greece", "Hungary", "Iceland", "Ireland", "Italy", "Latvia",
        "Liechtenstein", "Lithuania", "Luxembourg", "Malta", "Netherlands",
        "Norway", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia",
        "Spain", "Sweden",
    }
)
US_EXCHANGES = frozenset({"NASDAQ", "NYSE", "NYSE AMERICAN", "NYSE ARCA"})


class UniverseFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_market_cap: float | None = Field(default=None, ge=0)
    allowed_countries: list[str] = Field(default_factory=list)
    pea_focus_only: bool = False
    include_pea_review_required: bool = True


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    csv_path: Path | None = None
    csv_paths: list[Path] = Field(default_factory=list)
    filters: UniverseFilters = Field(default_factory=UniverseFilters)
    inline_universe_source_urls: str | None = None
    inline_universe_observation_date: date | None = None
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


def assess_pea_eligibility(security: Security) -> Security:
    """Attach a conservative, auditable PEA status without claiming broker eligibility.

    A native EEA listing is only a review candidate because listing country is
    not proof of the issuer's registered office, corporate-tax status, security
    type, or the broker's operational eligibility. Explicitly supplied statuses
    are preserved.
    """

    if security.pea_eligibility_status != PeaEligibilityStatus.UNKNOWN:
        return security
    listing_country = security.listing_country
    exchange = (security.exchange or "").strip().upper()
    native_eea_listing = bool(
        listing_country in EEA_COUNTRIES and exchange not in US_EXCHANGES
    )
    if not native_eea_listing:
        return security
    return security.model_copy(
        update={
            "pea_eligibility_status": PeaEligibilityStatus.REVIEW_REQUIRED,
            "pea_eligibility_basis": (
                "native EEA listing screen only; confirm issuer registered office, "
                "tax status, security type, and broker eligibility before purchase"
            ),
            "pea_eligibility_source_url": PEA_RULE_SOURCE_URL,
            "pea_eligibility_checked_at": PEA_RULE_CHECKED_AT,
        }
    )


def _apply_filters(securities: list[Security], filters: UniverseFilters) -> list[Security]:
    allowed = {country.casefold() for country in filters.allowed_countries}
    selected: list[Security] = []
    for security in securities:
        security = assess_pea_eligibility(security)
        if allowed and security.country and security.country.casefold() not in allowed:
            continue
        if filters.pea_focus_only:
            accepted = {PeaEligibilityStatus.CONFIRMED_ELIGIBLE}
            if filters.include_pea_review_required:
                accepted.add(PeaEligibilityStatus.REVIEW_REQUIRED)
            if security.pea_eligibility_status not in accepted:
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

    securities = [
        security.model_copy(
            update={
                "universe_source_urls": (
                    security.universe_source_urls or config.inline_universe_source_urls
                ),
                "universe_observation_date": (
                    security.universe_observation_date
                    or config.inline_universe_observation_date
                ),
            }
        )
        for security in config.securities
    ]
    csv_inputs = ([config.csv_path] if config.csv_path is not None else []) + config.csv_paths
    for configured_csv in csv_inputs:
        csv_path = (
            configured_csv
            if configured_csv.is_absolute()
            else (universe_path.parent / configured_csv).resolve()
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
