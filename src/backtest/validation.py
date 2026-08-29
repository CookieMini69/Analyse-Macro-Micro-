"""Strict look-ahead, survivorship, and point-in-time provenance gates."""

from __future__ import annotations

from datetime import date
import re

import pandas as pd

from src.models import BacktestValidationResult

SIGNAL_COLUMNS = {
    "ticker", "signal_date", "opportunity_score", "data_quality",
    "signal_available_at", "universe_snapshot_date", "source_archive_id",
    "point_in_time_validated", "archive_integrity_verified", "benchmark_ticker",
    "source_archive_sha256",
}
PRICE_COLUMNS = {"ticker", "observation_date", "adjusted_close"}


def validate_backtest_inputs(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    universe_snapshots: dict[date, set[str]],
    *,
    strict: bool = True,
) -> BacktestValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    missing_signals = SIGNAL_COLUMNS - set(signals.columns)
    missing_prices = PRICE_COLUMNS - set(prices.columns)
    if missing_signals:
        errors.append("missing signal columns: " + ", ".join(sorted(missing_signals)))
    if missing_prices:
        errors.append("missing price columns: " + ", ".join(sorted(missing_prices)))
    if errors:
        return _result(errors, warnings, False, False, False, False, False)

    frame = signals.copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce").dt.date
    frame["signal_available_at"] = pd.to_datetime(
        frame["signal_available_at"], errors="coerce", utc=True
    )
    frame["universe_snapshot_date"] = pd.to_datetime(
        frame["universe_snapshot_date"], errors="coerce"
    ).dt.date
    if frame[["signal_date", "signal_available_at", "universe_snapshot_date"]].isna().any().any():
        errors.append("signal dates contain invalid or missing values")
    if frame.duplicated(["ticker", "signal_date"]).any():
        errors.append("duplicate ticker/signal_date rows")
    scores = pd.to_numeric(frame["opportunity_score"], errors="coerce")
    if scores.isna().any() or ((scores < 0) | (scores > 100)).any():
        errors.append("opportunity_score must be numeric within 0..100")
    validated = frame["point_in_time_validated"].map(_truthy)
    archive_integrity = frame["archive_integrity_verified"].map(_truthy)
    archive_ids = frame["source_archive_id"].map(_present)
    archive_hashes = frame["source_archive_sha256"].map(
        lambda value: bool(re.fullmatch(r"[0-9a-f]{64}", str(value).strip().lower()))
    )
    point_in_time = bool(
        validated.all() and archive_integrity.all()
        and archive_ids.all() and archive_hashes.all()
    )
    if not point_in_time:
        errors.append(
            "every signal requires point_in_time_validated=true, "
            "archive_integrity_verified=true, source_archive_id, and a lowercase "
            "64-character source_archive_sha256"
        )

    valid_qualities = {"HIGH", "MEDIUM", "LOW", "UNAVAILABLE"}
    if not frame["data_quality"].astype(str).str.upper().isin(valid_qualities).all():
        errors.append("data_quality contains an unsupported value")
    benchmark_names = frame["benchmark_ticker"].map(_present)
    if not benchmark_names.all():
        errors.append("every signal requires a regional benchmark_ticker")

    look_ahead = True
    for row in frame.itertuples(index=False):
        if pd.isna(row.signal_date) or pd.isna(row.signal_available_at):
            look_ahead = False
            continue
        if row.signal_available_at.date() > row.signal_date:
            look_ahead = False
    if not look_ahead:
        errors.append("signal availability postdates signal_date")

    survivorship = True
    for row in frame.itertuples(index=False):
        snapshot_date = row.universe_snapshot_date
        members = universe_snapshots.get(snapshot_date)
        if (
            snapshot_date is None
            or row.signal_date is None
            or snapshot_date > row.signal_date
            or members is None
            or str(row.ticker).upper() not in members
        ):
            survivorship = False
    if not survivorship:
        errors.append("signals are not backed by eligible dated universe snapshots")

    price_frame = prices.copy()
    price_frame["observation_date"] = pd.to_datetime(
        price_frame["observation_date"], errors="coerce"
    ).dt.date
    price_frame["adjusted_close"] = pd.to_numeric(
        price_frame["adjusted_close"], errors="coerce"
    )
    price_frame["ticker"] = price_frame["ticker"].astype(str).str.strip().str.upper()
    future_prices_separated = not price_frame[
        ["observation_date", "adjusted_close"]
    ].isna().any().any()
    if not future_prices_separated or (price_frame["adjusted_close"] <= 0).any():
        errors.append("prices require valid dates and positive adjusted_close")
        future_prices_separated = False
    if price_frame.duplicated(["ticker", "observation_date"]).any():
        errors.append("duplicate ticker/observation_date price rows")
        future_prices_separated = False
    price_tickers = set(price_frame["ticker"])
    required_benchmarks = {
        str(value).strip().upper() for value in frame["benchmark_ticker"] if _present(value)
    }
    benchmark_data = bool(required_benchmarks) and required_benchmarks <= price_tickers
    if not benchmark_data:
        errors.append("one or more configured regional benchmarks have no price history")
    if strict and warnings:
        errors.extend(warnings)
    return _result(
        errors, warnings, look_ahead, survivorship, point_in_time,
        future_prices_separated, benchmark_data,
    )


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _present(value) -> bool:
    return not pd.isna(value) and str(value).strip().lower() not in {"", "nan", "none"}


def _result(
    errors, warnings, look_ahead, survivorship, point_in_time, future_prices,
    benchmark_data,
):
    return BacktestValidationResult(
        valid=not errors,
        look_ahead_free=look_ahead,
        survivorship_free=survivorship,
        point_in_time_inputs=point_in_time,
        future_prices_separated=future_prices,
        benchmark_data_complete=benchmark_data,
        errors=errors,
        warnings=warnings,
    )


__all__ = ["PRICE_COLUMNS", "SIGNAL_COLUMNS", "validate_backtest_inputs"]
