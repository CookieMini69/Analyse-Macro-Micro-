"""Write-once live signal archives for future point-in-time validation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.models import OpportunityCandidate, Security


def archive_live_run(
    results: list[OpportunityCandidate],
    securities: list[Security],
    *,
    as_of: datetime,
    archive_root: str | Path,
    archived_at: datetime | None = None,
) -> list[Path]:
    """Archive only a genuinely live run; reconstructed historical runs are skipped."""

    now = archived_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    if as_of.astimezone(UTC).date() != now.date():
        return []

    root = Path(archive_root)
    raw_directory = root / "source_archives"
    signal_directory = root / "signals"
    universe_directory = root / "universes"
    for directory in (raw_directory, signal_directory, universe_directory):
        directory.mkdir(parents=True, exist_ok=True)

    universe_path = universe_directory / f"{as_of.date().isoformat()}.csv"
    universe_rows = [
        {
            "ticker": security.ticker.upper(),
            "company": security.company,
            "country": security.country,
            "exchange": security.exchange,
            "currency": security.currency,
            "benchmark_ticker": security.benchmark,
        }
        for security in securities
    ]
    _write_universe_once(universe_path, universe_rows)

    payload = {
        "as_of": as_of.isoformat(),
        "archived_at": now.isoformat(),
        "universe_snapshot": universe_path.name,
        "methodology": "opportunity-scoring-v1",
        "results": [result.model_dump(mode="json") for result in results],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    source_path = raw_directory / f"scan_{stamp}_{digest[:12]}.json"
    if not source_path.exists():
        source_path.write_bytes(encoded)

    by_ticker = {security.ticker.upper(): security for security in securities}
    signal_rows = []
    for result in results:
        if result.opportunity_score is None:
            continue
        security = by_ticker.get(result.ticker.upper())
        benchmark = security.benchmark if security is not None else None
        signal_rows.append(
            {
                "ticker": result.ticker.upper(),
                "signal_date": as_of.date().isoformat(),
                "opportunity_score": result.opportunity_score,
                "data_quality": result.data_quality.value,
                "signal_available_at": now.isoformat(),
                "universe_snapshot_date": as_of.date().isoformat(),
                "source_archive_id": source_path.name,
                "source_archive_sha256": digest,
                "point_in_time_validated": True,
                "benchmark_ticker": benchmark,
            }
        )
    signal_path = signal_directory / f"signals_{stamp}_{digest[:12]}.csv"
    pd.DataFrame(signal_rows, columns=[
        "ticker", "signal_date", "opportunity_score", "data_quality",
        "signal_available_at", "universe_snapshot_date", "source_archive_id",
        "source_archive_sha256", "point_in_time_validated", "benchmark_ticker",
    ]).to_csv(signal_path, index=False)
    return [universe_path, source_path, signal_path]


def _write_universe_once(path: Path, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)
    if path.exists():
        existing = pd.read_csv(path).fillna("")
        candidate = frame.fillna("")
        if not existing.equals(candidate):
            raise ValueError(
                f"dated universe snapshot already exists with different membership: {path}"
            )
        return
    frame.to_csv(path, index=False)


__all__ = ["archive_live_run"]
