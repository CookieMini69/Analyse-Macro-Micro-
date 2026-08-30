"""Build a dated snapshot of US-listed, SEC-reporting equity instruments.

The listing population comes from Nasdaq Trader's current symbol directories.
CIK, conformed issuer name and exchange are joined from the SEC's official
ticker/exchange association file. ETFs, tests and clearly non-equity units,
warrants, rights, preferred shares and debt instruments are excluded. The
result is an auditable *current* snapshot, not a survivorship-free history.
"""

from __future__ import annotations

import argparse
import os
import re
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

EXCHANGE_NAMES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}

NON_COMMON_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwarrants?\b",
        r"\brights?\b",
        r"\bunits?\b",
        r"\bpreferred\b",
        r"\bnotes?\b",
        r"\bbonds?\b",
        r"\bdebentures?\b",
        r"\bETNs?\b",
    )
)


def _get_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def _directory_date(text: str) -> date:
    match = re.search(r"File Creation Time:\s*(\d{8})", text)
    if not match:
        raise RuntimeError("Nasdaq directory has no parseable creation timestamp")
    return datetime.strptime(match.group(1), "%m%d%Y").date()


def _clean_directory(text: str) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(text), sep="|")
    first = frame.columns[0]
    return frame[~frame[first].astype(str).str.startswith("File Creation Time:")].copy()


def _is_common_equity(name: object) -> bool:
    value = str(name or "")
    return bool(value) and not any(pattern.search(value) for pattern in NON_COMMON_PATTERNS)


def _configured_tickers(config_path: Path) -> set[str]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    tickers = {
        str(item.get("ticker", "")).strip().upper()
        for item in raw.get("securities", [])
        if item.get("ticker")
    }
    for configured in ([raw.get("csv_path")] if raw.get("csv_path") else []) + list(raw.get("csv_paths", [])):
        path = Path(configured)
        path = path if path.is_absolute() else config_path.parent / path
        if path.exists() and path.name != "universe_us_listed.csv":
            frame = pd.read_csv(path, usecols=["ticker"])
            tickers.update(frame["ticker"].dropna().astype(str).str.upper())
    return tickers


def build_snapshot(
    *,
    session: requests.Session | None = None,
    config_path: str | Path = "config/universe.yaml",
) -> pd.DataFrame:
    client = session or requests.Session()
    config_file = Path(config_path).resolve()
    load_dotenv(config_file.parents[1] / ".env", override=False)
    user_agent = os.getenv("SEC_USER_AGENT", "AI Stock Opportunity Scanner research contact@example.com")
    client.headers.update({"User-Agent": user_agent})

    nasdaq_text = _get_text(client, NASDAQ_LISTED_URL)
    other_text = _get_text(client, OTHER_LISTED_URL)
    snapshot_date = min(_directory_date(nasdaq_text), _directory_date(other_text))
    nasdaq = _clean_directory(nasdaq_text)
    other = _clean_directory(other_text)

    nasdaq = nasdaq[
        nasdaq["Test Issue"].eq("N")
        & nasdaq["ETF"].eq("N")
        & nasdaq["NextShares"].eq("N")
        & nasdaq["Security Name"].map(_is_common_equity)
    ]
    nasdaq_rows = pd.DataFrame(
        {
            "ticker": nasdaq["Symbol"],
            "listing_name": nasdaq["Security Name"],
            "directory_exchange": "Nasdaq",
        }
    )
    other = other[
        other["Test Issue"].eq("N")
        & other["ETF"].eq("N")
        & other["Security Name"].map(_is_common_equity)
    ]
    other_rows = pd.DataFrame(
        {
            "ticker": other["NASDAQ Symbol"],
            "listing_name": other["Security Name"],
            "directory_exchange": other["Exchange"].map(EXCHANGE_NAMES).fillna(other["Exchange"]),
        }
    )
    listings = pd.concat([nasdaq_rows, other_rows], ignore_index=True)
    listings["ticker"] = listings["ticker"].astype(str).str.strip().str.upper()

    sec_response = client.get(SEC_TICKERS_URL, timeout=60)
    sec_response.raise_for_status()
    payload = sec_response.json()
    sec = pd.DataFrame(payload["data"], columns=payload["fields"])
    sec["ticker"] = sec["ticker"].astype(str).str.strip().str.upper()
    sec = sec.drop_duplicates("ticker", keep="first")
    joined = listings.merge(sec[["ticker", "cik", "name", "exchange"]], on="ticker", how="inner")
    joined = joined.drop_duplicates("ticker", keep="first")
    excluded = _configured_tickers(config_file)
    joined = joined[~joined["ticker"].isin(excluded)].copy()

    source_urls = f"{NASDAQ_LISTED_URL};{OTHER_LISTED_URL};{SEC_TICKERS_URL}"
    result = pd.DataFrame(
        {
            "ticker": joined["ticker"],
            "cik": joined["cik"].astype(str),
            "company": joined["name"].fillna(joined["listing_name"]),
            "country": "United States",
            "listing_country": "United States",
            "country_basis": "listing_market",
            "region": "North America",
            "sector": None,
            "exchange": joined["exchange"].fillna(joined["directory_exchange"]),
            "currency": "USD",
            "benchmark": "^GSPC",
            "sector_benchmark": None,
            "index_memberships": None,
            "universe_source_urls": source_urls,
            "universe_observation_date": snapshot_date.isoformat(),
            "price_scale": 1.0,
            "price_scale_reason": None,
        }
    )
    return result.sort_values("ticker").reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="config/universe_us_listed.csv")
    parser.add_argument("--config", default="config/universe.yaml")
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame = build_snapshot(config_path=args.config)
    frame.to_csv(destination, index=False)
    print(f"{destination}: {len(frame)} SEC-reporting US-listed equity instruments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

