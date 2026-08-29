"""Load archived signals, outcome prices, and dated universe snapshots."""

from __future__ import annotations

import re
import hashlib
from datetime import date
from pathlib import Path

import pandas as pd


def load_backtest_inputs(
    signals_path: str | Path,
    prices_path: str | Path,
    universe_directory: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[date, set[str]]]:
    signal_path = Path(signals_path)
    signals = _load_csv_path(signal_path, {"ticker", "signal_date"})
    signals = _verify_source_archives(signals, signal_path)
    prices = _load_csv_path(Path(prices_path), {"ticker", "observation_date"})
    snapshots = load_universe_snapshots(universe_directory)
    return signals, prices, snapshots


def _load_csv_path(path: Path, required: set[str]) -> pd.DataFrame:
    paths = sorted(path.glob("*.csv")) if path.is_dir() else [path]
    frames = []
    for csv_path in paths:
        frame = pd.read_csv(csv_path)
        if required <= set(frame.columns):
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=sorted(required))
    return pd.concat(frames, ignore_index=True)


def _verify_source_archives(signals: pd.DataFrame, signal_path: Path) -> pd.DataFrame:
    frame = signals.copy()
    verified: list[bool] = []
    signal_directory = signal_path if signal_path.is_dir() else signal_path.parent
    archive_directory = (
        signal_directory.parent / "source_archives"
        if signal_directory.name == "signals"
        else signal_directory / "source_archives"
    )
    for row in frame.itertuples(index=False):
        archive_id = str(getattr(row, "source_archive_id", "")).strip()
        expected = str(getattr(row, "source_archive_sha256", "")).strip().lower()
        safe_name = Path(archive_id).name == archive_id and archive_id not in {"", ".", ".."}
        archive_path = archive_directory / archive_id
        digest = (
            hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if safe_name and archive_path.is_file()
            else None
        )
        original = str(getattr(row, "point_in_time_validated", "")).lower() in {
            "true", "1", "yes"
        }
        verified.append(bool(original and digest == expected))
    frame["archive_integrity_verified"] = verified
    return frame


def load_universe_snapshots(directory: str | Path) -> dict[date, set[str]]:
    root = Path(directory)
    if not root.exists():
        return {}
    snapshots: dict[date, set[str]] = {}
    for path in sorted(root.glob("*.csv")):
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})", path.stem)
        if match is None:
            continue
        frame = pd.read_csv(path)
        if "ticker" not in frame:
            continue
        snapshot_date = date.fromisoformat(match.group(1))
        snapshots[snapshot_date] = {
            str(value).strip().upper()
            for value in frame["ticker"].dropna()
            if str(value).strip()
        }
    return snapshots


__all__ = ["load_backtest_inputs", "load_universe_snapshots"]
