"""Build a dated native-listing equity universe from free official directories.

This module deliberately keeps listing membership separate from issuer domicile.
The files below prove that a security was present in an exchange directory on a
given date; they do not prove index membership, PEA eligibility, or complete
historical survivorship coverage.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Callable

import pandas as pd
import requests


@dataclass(frozen=True)
class OfficialUniverseSource:
    key: str
    url: str
    listing_country: str
    region: str
    exchange: str
    currency: str
    benchmark: str
    parser: Callable[[bytes], tuple[pd.DataFrame, date]]


def _date_from_value(value: object, fallback: date) -> date:
    parsed = pd.to_datetime(value, errors="coerce")
    return fallback if pd.isna(parsed) else parsed.date()


def parse_jpx(content: bytes) -> tuple[pd.DataFrame, date]:
    raw = pd.read_excel(io.BytesIO(content), dtype=str)
    raw.columns = [str(column).strip() for column in raw.columns]
    equity = raw[raw["市場・商品区分"].str.contains("株式|PRO Market", na=False)].copy()
    result = pd.DataFrame({
        "ticker": equity["コード"].str.strip() + ".T",
        "company": equity["銘柄名"].str.strip(),
        "sector": equity.get("17業種区分"),
        "index_memberships": None,
    })
    observed = _date_from_value(raw["日付"].dropna().iloc[0], date.today())
    return result, observed


def parse_nse(content: bytes) -> tuple[pd.DataFrame, date]:
    raw = pd.read_csv(io.BytesIO(content), dtype=str)
    raw.columns = [str(column).strip() for column in raw.columns]
    series = raw.get("SERIES", pd.Series("EQ", index=raw.index)).str.strip()
    equity = raw[series.eq("EQ")].copy()
    result = pd.DataFrame({
        "ticker": equity["SYMBOL"].str.strip() + ".NS",
        "company": equity["NAME OF COMPANY"].str.strip(),
        "sector": None,
        "index_memberships": None,
    })
    # The current NSE file does not embed its publication timestamp. Retrieval
    # date is therefore the conservative observation date disclosed in lineage.
    return result, date.today()


ASX_COMMON_TYPES = frozenset({
    "ORDINARY FULLY PAID",
    "ORDINARY FULLY PAID FOREIGN EXEMPT NZX",
    "CHESS DEPOSITARY INTERESTS 1:1",
    "COMMON SHARES",
    "COMMON STOCK",
    "FULLY PAID ORDINARY/UNITS STAPLED SECURITIES",
})


def parse_asx(content: bytes) -> tuple[pd.DataFrame, date]:
    raw = pd.read_excel(io.BytesIO(content), dtype=str)
    raw.columns = [str(column).strip() for column in raw.columns]
    code = raw["ASX code"].fillna("").str.strip().str.upper()
    security_type = raw["Security type"].fillna("").str.strip().str.upper()
    equity = raw[security_type.isin(ASX_COMMON_TYPES) & code.str.fullmatch(r"[A-Z0-9]{3}")].copy()
    result = pd.DataFrame({
        "ticker": equity["ASX code"].str.strip().str.upper() + ".AX",
        "company": equity["Company name"].str.strip(),
        "sector": None,
        "index_memberships": None,
    })
    marker = str(raw.iloc[2, 0]) if len(raw) > 2 else ""
    match = re.search(r"(\d{2}/\d{2}/\d{4})", marker)
    observed = datetime.strptime(match.group(1), "%d/%m/%Y").date() if match else date.today()
    return result, observed


def parse_hkex(content: bytes) -> tuple[pd.DataFrame, date]:
    header = pd.read_excel(io.BytesIO(content), header=None, nrows=2, dtype=str)
    marker = " ".join(header.fillna("").astype(str).to_numpy().ravel())
    raw = pd.read_excel(io.BytesIO(content), skiprows=2, dtype=str)
    raw.columns = [str(column).strip() for column in raw.columns]
    equity = raw[raw["Category"].fillna("").str.strip().eq("Equity")].copy()

    def yahoo_hk(code: object) -> str | None:
        digits = re.sub(r"\D", "", str(code))
        if not digits:
            return None
        return f"{int(digits):04d}.HK"

    result = pd.DataFrame({
        "ticker": equity["Stock Code"].map(yahoo_hk),
        "company": equity["Name of Securities"].str.strip(),
        "sector": None,
        "index_memberships": None,
    })
    match = re.search(r"(\d{2}/\d{2}/\d{4})", marker)
    observed = datetime.strptime(match.group(1), "%d/%m/%Y").date() if match else date.today()
    return result, observed


SOURCES = (
    OfficialUniverseSource(
        "jpx", "https://www.jpx.co.jp/markets/statistics-equities/misc/"
        "tvdivq0000001vg2-att/data_j.xls", "Japan", "Asia Pacific", "Tokyo Stock Exchange",
        "JPY", "^N225", parse_jpx,
    ),
    OfficialUniverseSource(
        "nse", "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "India", "Asia Pacific", "National Stock Exchange of India", "INR", "^NSEI", parse_nse,
    ),
    OfficialUniverseSource(
        "asx", "https://www.asx.com.au/content/dam/asx/issuers/ISIN.xls",
        "Australia", "Asia Pacific", "Australian Securities Exchange", "AUD", "^AXJO", parse_asx,
    ),
    OfficialUniverseSource(
        "hkex", "https://www.hkex.com.hk/eng/services/trading/securities/"
        "securitieslists/ListOfSecurities.xlsx", "Hong Kong", "Asia Pacific",
        "Hong Kong Stock Exchange", "HKD", "^HSI", parse_hkex,
    ),
)


def build_world_snapshot(
    *, session: requests.Session | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Download, normalize and combine native official exchange directories."""

    client = session or requests.Session()
    client.headers.update({"User-Agent": "AI Stock Opportunity Scanner/2.0 research universe"})
    retrieved_at = datetime.now(UTC)
    frames: list[pd.DataFrame] = []
    lineage: list[dict[str, object]] = []
    for source in SOURCES:
        response = client.get(source.url, timeout=90)
        response.raise_for_status()
        parsed, observed = source.parser(response.content)
        parsed = parsed.dropna(subset=["ticker"]).copy()
        parsed["ticker"] = parsed["ticker"].astype(str).str.strip().str.upper()
        parsed = parsed[parsed["ticker"].ne("")].drop_duplicates("ticker")
        parsed["cik"] = None
        parsed["country"] = source.listing_country
        parsed["listing_country"] = source.listing_country
        parsed["country_basis"] = "listing_market_only; issuer_domicile_not_inferred"
        parsed["region"] = source.region
        parsed["exchange"] = source.exchange
        parsed["currency"] = source.currency
        parsed["benchmark"] = source.benchmark
        parsed["sector_benchmark"] = None
        parsed["universe_source_urls"] = source.url
        parsed["universe_observation_date"] = observed.isoformat()
        parsed["price_scale"] = 1.0
        parsed["price_scale_reason"] = None
        frames.append(parsed)
        lineage.append({
            "source": source.key,
            "url": source.url,
            "listing_country": source.listing_country,
            "observation_date": observed.isoformat(),
            "retrieved_at": retrieved_at.isoformat(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "raw_bytes": len(response.content),
            "equity_rows": len(parsed),
        })
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates("ticker", keep="first").sort_values("ticker")
    columns = [
        "ticker", "cik", "company", "country", "listing_country", "country_basis",
        "region", "sector", "exchange", "currency", "benchmark", "sector_benchmark",
        "index_memberships", "universe_source_urls", "universe_observation_date",
        "price_scale", "price_scale_reason",
    ]
    audit = {
        "schema_version": 1,
        "generated_at": retrieved_at.isoformat(),
        "definition": "current common-equity native listings from free official directories",
        "rows": len(combined),
        "sources": lineage,
        "world_complete": False,
        "world_complete_reason": (
            "No free source proves exhaustive current and delisted equity coverage for every "
            "exchange worldwide; this manifest reports only verified directories."
        ),
    }
    return combined[columns].reset_index(drop=True), audit


__all__ = [
    "ASX_COMMON_TYPES", "SOURCES", "build_world_snapshot", "parse_asx",
    "parse_hkex", "parse_jpx", "parse_nse",
]
