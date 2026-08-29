"""Build a dated European blue-chip universe snapshot.

Wikipedia constituent tables are used as a reproducible public snapshot input,
not as an exchange-grade point-in-time feed. The generated CSV retains each
source URL and observation date so later audits never confuse it with historical
membership. Yahoo-compatible listing symbols are normalized deterministically.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests


@dataclass(frozen=True, slots=True)
class IndexSpec:
    name: str
    page: str
    rows: int
    expected: int
    company_column: str
    ticker_column: str
    sector_column: str
    listing_country: str
    exchange: str
    currency: str
    benchmark: str
    suffix: str = ""

    @property
    def url(self) -> str:
        return f"https://en.wikipedia.org/wiki/{self.page}"


INDEX_SPECS = (
    IndexSpec("CAC 40", "CAC_40", 40, 40, "Company", "Ticker", "Sector", "France", "Euronext Paris", "EUR", "^FCHI"),
    IndexSpec("DAX 40", "DAX", 40, 40, "Company", "Ticker", "Prime Standard Sector", "Germany", "Xetra", "EUR", "^GDAXI"),
    IndexSpec("FTSE 100", "FTSE_100_Index", 100, 100, "Company", "Ticker", "FTSE industry classification benchmark sector[39]", "United Kingdom", "London Stock Exchange", "GBP", "^FTSE", ".L"),
    IndexSpec("AEX 25", "AEX_index", 25, 25, "Company", "Ticker", "ICB Sector", "Netherlands", "Euronext Amsterdam", "EUR", "^AEX"),
    IndexSpec("BEL 20", "BEL_20", 20, 20, "Company", "Ticker symbol", "ICB Sector", "Belgium", "Euronext Brussels", "EUR", "^BFX"),
    IndexSpec("SMI 20", "Swiss_Market_Index", 21, 20, "Name", "Ticker", "Sector", "Switzerland", "SIX Swiss Exchange", "CHF", "^SSMI", ".SW"),
    IndexSpec("IBEX 35", "IBEX_35", 35, 35, "Company", "Ticker", "Sector", "Spain", "Bolsa de Madrid", "EUR", "^IBEX"),
    IndexSpec("FTSE MIB 40", "FTSE_MIB", 40, 40, "Company", "Ticker", "ICB Sector", "Italy", "Borsa Italiana", "EUR", "FTSEMIB.MI"),
    IndexSpec("OMX Stockholm 30", "OMX_Stockholm_30", 30, 30, "Company", "Ticker", "GICS sector", "Sweden", "Nasdaq Stockholm", "SEK", "^OMX"),
    IndexSpec("OMX Copenhagen 25", "OMX_Copenhagen_25", 25, 25, "Company", "Ticker symbol", "ICB Sector", "Denmark", "Nasdaq Copenhagen", "DKK", "^OMXC25", ".CO"),
    IndexSpec("OMX Helsinki 25", "OMX_Helsinki_25", 25, 25, "Company", "Ticker", "GICS sector", "Finland", "Nasdaq Helsinki", "EUR", "^OMXH25"),
    # Yahoo does not expose the OBX price index reliably; OBXD.OL is the DNB
    # OBX ETF proxy and is labeled as such in the compliance documentation.
    IndexSpec("OBX 25", "OBX_Index", 25, 25, "Company", "Ticker symbol", "ICB subsector", "Norway", "Oslo Bors", "NOK", "OBXD.OL", ".OL"),
    IndexSpec("PSI", "PSI-20", 16, 16, "Company", "Ticker", "Industry", "Portugal", "Euronext Lisbon", "EUR", "PSI20.LS", ".LS"),
)


CIK_BY_TICKER = {
    "ASML.AS": "937966",
    "AZN.L": "901832",
    "BP.L": "313807",
    "DGE.L": "835403",
    "GSK.L": "1131399",
    "NVO-B.CO": "353278",
    "NVS.SW": "1114448",
    "RIO.L": "863064",
    "SAP.DE": "1000184",
    "SHEL.L": "1306965",
    "SNY.PA": "1121404",
    "TTE.PA": "879764",
    "UBSG.SW": "1610520",
    "ULVR.L": "217410",
}


# Current-symbol corporate actions that the public tables can lag. Every
# override retains an official issuer/exchange source in the generated row.
TICKER_OVERRIDES = {
    ("OMX Copenhagen 25", "NDA"): (
        "NDA-DK",
        None,
        "https://view.news.eu.nasdaq.com/view?id=ba970a92a1ae2b95ffb13144306dcf48e&lang=en&src=rss",
    ),
    ("OMX Helsinki 25", "KOJAMO.HE"): (
        "LUMO.HE",
        "Lumo Homes Plc",
        "https://view.news.eu.nasdaq.com/view?id=b0f37e430d4f3cb0c18b367d364b9ffc3&lang=en",
    ),
    ("OBX 25", "GOGL"): (
        "CMBTO",
        "CMB.TECH NV",
        "https://live.euronext.com/en/products/equities/company-news/2025-08-20-cmbtech-completes-merger-golden-ocean",
    ),
    ("SMI 20", "ROP"): (
        "ROP",
        None,
        "https://www.roche.com/investors/updates/inv-update-2026-03-16",
    ),
}


PSI_SOURCE_URL = "https://live.euronext.com/en/product/indices/pting0200002-xlis/market-information"
PSI_OFFICIAL = (
    ("ALTR", "Altri SGPS", "Materials"),
    ("BCP", "Banco Comercial Português", "Financials"),
    ("COR", "Corticeira Amorim", "Materials"),
    ("CTT", "CTT Correios de Portugal", "Industrials"),
    ("EDP", "Energias de Portugal", "Utilities"),
    ("EDPR", "EDP Renováveis", "Utilities"),
    ("GALP", "Galp Energia", "Energy"),
    ("IBS", "Ibersol", "Consumer Discretionary"),
    ("JMT", "Jerónimo Martins", "Consumer Staples"),
    ("EGL", "Mota-Engil", "Industrials"),
    ("NOS", "NOS", "Communication Services"),
    ("RENE", "Redes Energéticas Nacionais", "Utilities"),
    ("SEM", "Semapa", "Materials"),
    ("SON", "Sonae", "Consumer Staples"),
    ("TDSA", "Teixeira Duarte", "Industrials"),
    ("NVG", "The Navigator Company", "Materials"),
)


def _fetch_tables(spec: IndexSpec, session: requests.Session) -> pd.DataFrame:
    response = session.get(spec.url, timeout=45)
    response.raise_for_status()
    response.encoding = "utf-8"
    tables = pd.read_html(StringIO(response.text))
    matches = [
        table
        for table in tables
        if len(table) == spec.rows
        and spec.company_column in table.columns
        and spec.ticker_column in table.columns
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{spec.name}: expected one constituent table, got {len(matches)}")
    return matches[0]


def _ticker(raw: object, spec: IndexSpec) -> str | None:
    if pd.isna(raw):
        return None
    value = re.sub(r"\[[^]]+\]", "", str(raw)).strip()
    if not value:
        return None
    if spec.name == "BEL 20":
        market, value = value.rsplit(":", 1)
        value = re.sub(r"^[^A-Za-z0-9]+", "", value).strip()
        return value + (".AS" if "Amsterdam" in market else ".BR")
    if spec.name == "OBX 25":
        value = value.split(":", 1)[-1].strip()
    override = TICKER_OVERRIDES.get((spec.name, value.upper()))
    if override:
        value = override[0]
    if spec.suffix:
        if spec.name == "FTSE 100":
            value = value.replace(".", "-")
        elif spec.name == "OMX Copenhagen 25":
            value = value.replace(" ", "-")
        if not value.endswith(spec.suffix):
            value += spec.suffix
    return value.upper()


def _text(raw: object) -> str | None:
    if pd.isna(raw):
        return None
    value = re.sub(r"\[[^]]+\]", "", str(raw)).strip()
    return value or None


def _sector(raw: object) -> str | None:
    value = (_text(raw) or "").casefold()
    groups = (
        ("Information Technology", ("technology", "software", "semiconductor", "electronic")),
        ("Health Care", ("health", "pharma", "medical")),
        ("Financials", ("bank", "financial", "insurance", "investment")),
        ("Energy", ("energy", "oil", "gas", "drilling")),
        ("Utilities", ("utilit", "electricity", "water")),
        ("Materials", ("material", "chemical", "mining", "aluminum", "fertilizer", "basic resources")),
        ("Real Estate", ("real estate",)),
        ("Communication Services", ("telecom", "communication", "media")),
        ("Consumer Staples", ("food", "beverage", "tobacco", "grocery", "personal care", "retail staples")),
        ("Consumer Discretionary", ("consumer", "retail discretionary", "travel", "leisure", "automobile")),
        ("Industrials", ("industrial", "construction", "transport", "aerospace", "machinery")),
    )
    for sector, terms in groups:
        if any(term in value for term in terms):
            return sector
    return _text(raw)


def build_snapshot(snapshot_date: date, session: requests.Session | None = None) -> pd.DataFrame:
    client = session or requests.Session()
    client.headers.update({"User-Agent": "AI Stock Opportunity Scanner universe audit/1.1"})
    by_ticker: dict[str, dict[str, object]] = {}
    for spec in INDEX_SPECS:
        if spec.name == "PSI":
            table = pd.DataFrame(
                PSI_OFFICIAL,
                columns=[spec.ticker_column, spec.company_column, spec.sector_column],
            )
        else:
            table = _fetch_tables(spec, client)
        seen = 0
        for _, raw in table.iterrows():
            ticker = _ticker(raw[spec.ticker_column], spec)
            company = _text(raw[spec.company_column])
            if not ticker or not company:
                continue
            raw_ticker = re.sub(r"\[[^]]+\]", "", str(raw[spec.ticker_column])).strip().upper()
            raw_ticker = raw_ticker.split(":")[-1].strip()
            override = TICKER_OVERRIDES.get((spec.name, raw_ticker))
            if override and override[1]:
                company = override[1]
            source_urls = [PSI_SOURCE_URL if spec.name == "PSI" else spec.url]
            if override:
                source_urls.append(override[2])
            seen += 1
            record = by_ticker.get(ticker)
            if record is None:
                record = {
                    "ticker": ticker,
                    "cik": CIK_BY_TICKER.get(ticker),
                    "company": company,
                    "country": spec.listing_country,
                    "listing_country": spec.listing_country,
                    "country_basis": "listing_market",
                    "region": "Europe",
                    "sector": _sector(raw.get(spec.sector_column)),
                    "exchange": spec.exchange,
                    "currency": spec.currency,
                    "benchmark": spec.benchmark,
                    "sector_benchmark": None,
                    "index_memberships": spec.name,
                    "universe_source_urls": ";".join(source_urls),
                    "universe_observation_date": snapshot_date.isoformat(),
                    "price_scale": 0.01 if spec.currency == "GBP" else 1.0,
                    "price_scale_reason": (
                        "London Stock Exchange Yahoo quotes are expressed in GBp; convert pence to GBP"
                        if spec.currency == "GBP"
                        else None
                    ),
                }
                by_ticker[ticker] = record
            else:
                memberships = set(str(record["index_memberships"]).split(";"))
                memberships.add(spec.name)
                record["index_memberships"] = ";".join(sorted(memberships))
                urls = set(str(record["universe_source_urls"]).split(";"))
                urls.add(spec.url)
                record["universe_source_urls"] = ";".join(sorted(urls))
        if seen != spec.expected:
            raise RuntimeError(f"{spec.name}: expected {spec.expected} constituents, got {seen}")
    columns = [
        "ticker", "cik", "company", "country", "listing_country", "country_basis",
        "region", "sector", "exchange", "currency", "benchmark",
        "sector_benchmark", "index_memberships", "universe_source_urls",
        "universe_observation_date", "price_scale", "price_scale_reason",
    ]
    return pd.DataFrame(by_ticker.values(), columns=columns).sort_values(
        ["listing_country", "ticker"]
    ).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="config/universe_europe.csv")
    parser.add_argument("--snapshot-date", default=date.today().isoformat())
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame = build_snapshot(date.fromisoformat(args.snapshot_date))
    frame.to_csv(destination, index=False)
    print(f"{destination}: {len(frame)} unique securities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
