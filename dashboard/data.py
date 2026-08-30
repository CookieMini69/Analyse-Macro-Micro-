"""Pure, testable data-access helpers for the Streamlit dashboard."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SCAN_COLUMNS = {"ticker", "is_candidate", "drawdown_52w"}
JSON_COLUMNS = {
    "fx_metrics", "fundamental_metrics", "valuation_metrics", "shock_metrics",
    "historical_metrics", "scenario_metrics", "scoring_metrics",
    "candidate_reasons", "fundamental_invalidation", "shock_missing_criteria",
    "metric_statuses", "missing_metrics", "sources",
}
LIST_COLUMNS = {
    "candidate_reasons", "fundamental_invalidation", "shock_missing_criteria",
    "missing_metrics", "sources",
}


class DashboardDataError(ValueError):
    """Raised when a generated scan artifact is unreadable or incomplete."""


def latest_scan_report(reports_dir: str | Path | None = None) -> Path | None:
    directory = Path(reports_dir) if reports_dir else PROJECT_ROOT / "reports"
    matches = sorted(
        directory.glob("stock_opportunity_scan_*.csv"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    # A pipeline interruption can leave a truncated newest CSV. Do not make the
    # whole dashboard unusable when an earlier complete immutable report exists.
    for path in matches:
        try:
            preview = pd.read_csv(path, nrows=1)
            columns = set(preview.columns)
        except (OSError, UnicodeError, pd.errors.ParserError):
            continue
        if REQUIRED_SCAN_COLUMNS <= columns and not preview.empty:
            return path
    return None


def _decode_json(value: Any, fallback: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return fallback


def load_scan_report(path: str | Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise DashboardDataError(f"rapport illisible: {exc}") from exc
    missing = REQUIRED_SCAN_COLUMNS - set(frame.columns)
    if missing:
        raise DashboardDataError(
            "rapport incomplet, colonnes absentes: " + ", ".join(sorted(missing))
        )
    if frame.empty:
        raise DashboardDataError("rapport vide")
    for column in JSON_COLUMNS & set(frame.columns):
        fallback: list[Any] | dict[str, Any] = [] if column in LIST_COLUMNS else {}
        frame[column] = frame[column].map(lambda value, default=fallback: _decode_json(value, default))
    if "listing_country" in frame and "country" in frame:
        frame["listing_country"] = frame["listing_country"].fillna(frame["country"])
    for column in (
        "country", "listing_country", "sector", "index_memberships",
        "pea_eligibility_status",
    ):
        if column in frame:
            frame[column] = frame[column].fillna("Non renseigné")
    return frame


def filter_scan(
    frame: pd.DataFrame,
    *,
    countries: list[str] | None = None,
    sectors: list[str] | None = None,
    indices: list[str] | None = None,
    minimum_score: float = 0.0,
    maximum_drawdown: float = 0.0,
    minimum_market_cap_eur: float = 0.0,
    shock_natures: list[str] | None = None,
    minimum_risk_score: float = 0.0,
    query: str | None = None,
    candidates_only: bool = False,
    pea_statuses: list[str] | None = None,
) -> pd.DataFrame:
    selected = pd.Series(True, index=frame.index)
    country_column = "listing_country" if "listing_country" in frame else "country"
    if countries:
        selected &= frame[country_column].isin(countries)
    if sectors:
        selected &= frame["sector"].isin(sectors)
    if indices and "index_memberships" in frame:
        selected &= frame["index_memberships"].map(
            lambda value: bool(set(indices) & set(str(value).split(";")))
        )
    if minimum_score > 0 and "opportunity_score" in frame:
        selected &= pd.to_numeric(frame["opportunity_score"], errors="coerce").fillna(-1) >= minimum_score
    if "drawdown_52w" in frame:
        selected &= pd.to_numeric(frame["drawdown_52w"], errors="coerce").fillna(1) <= maximum_drawdown
    if minimum_market_cap_eur > 0 and "market_cap_eur" in frame:
        selected &= pd.to_numeric(frame["market_cap_eur"], errors="coerce").fillna(-1) >= minimum_market_cap_eur
    if shock_natures and "shock_nature" in frame:
        selected &= frame["shock_nature"].fillna("data_unavailable").isin(shock_natures)
    if minimum_risk_score > 0 and "risk_score" in frame:
        selected &= pd.to_numeric(frame["risk_score"], errors="coerce").fillna(-1) >= minimum_risk_score
    if candidates_only and "is_candidate" in frame:
        selected &= frame["is_candidate"].fillna(False).astype(bool)
    if pea_statuses and "pea_eligibility_status" in frame:
        selected &= frame["pea_eligibility_status"].isin(pea_statuses)
    normalized_query = (query or "").strip().casefold()
    if normalized_query:
        searchable = [
            column for column in (
                "ticker", "company", "country", "listing_country", "region",
                "sector", "exchange", "index_memberships",
                "pea_eligibility_status",
            )
            if column in frame
        ]
        matches = pd.Series(False, index=frame.index)
        for column in searchable:
            matches |= frame[column].fillna("").astype(str).str.casefold().str.contains(
                normalized_query, regex=False
            )
        selected &= matches
    return frame.loc[selected].copy()


def index_choices(frame: pd.DataFrame) -> list[str]:
    choices: set[str] = set()
    if "index_memberships" in frame:
        for raw in frame["index_memberships"].dropna():
            choices.update(item for item in str(raw).split(";") if item and item != "Non renseigné")
    return sorted(choices)


def safe_ticker_name(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ticker)


def load_price_history(ticker: str, processed_dir: str | Path | None = None) -> pd.DataFrame:
    directory = Path(processed_dir) if processed_dir else PROJECT_ROOT / "data" / "processed" / "prices"
    path = directory / f"{safe_ticker_name(ticker)}.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, parse_dates=["observation_date"])
    price_column = "adjusted_close" if "adjusted_close" in frame else "close"
    prices = pd.to_numeric(frame[price_column], errors="coerce")
    frame["ma50"] = prices.rolling(50, min_periods=20).mean()
    frame["ma200"] = prices.rolling(200, min_periods=60).mean()
    frame["running_peak"] = prices.cummax()
    frame["drawdown"] = prices / frame["running_peak"] - 1.0
    return frame


def load_latest_fundamental(ticker: str, fundamentals_dir: str | Path | None = None) -> dict[str, Any] | None:
    directory = Path(fundamentals_dir) if fundamentals_dir else PROJECT_ROOT / "data" / "processed" / "fundamentals"
    matches = list(directory.glob(f"{safe_ticker_name(ticker)}__asof_*.json"))
    if not matches:
        return None
    latest = max(matches, key=lambda path: path.stat().st_mtime)
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scenario_rows(payload: dict[str, Any], horizon: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, case in (payload.get("cases") or {}).items():
        point = next((item for item in case.get("horizons", []) if item.get("months") == horizon), {})
        target = point.get("target_price") or {}
        rows.append({
            "Scénario": str(name).title(), "Horizon": f"{horizon} mois",
            "Objectif": target.get("value"),
            "Statut": target.get("status", case.get("status", "data_unavailable")),
            "Couverture": case.get("assumption_coverage"),
        })
    return rows

