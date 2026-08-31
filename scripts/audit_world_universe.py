"""Audit configured world coverage without downloading market data."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from src.screening.universe import load_universe


KNOWN_FREE_GAPS = [
    "Canada native listings",
    "mainland China native listings",
    "Korea and Taiwan native listings",
    "Latin America native listings beyond configured ADRs",
    "Africa native listings beyond configured ADRs",
    "survivorship-free worldwide delistings and historical ticker mappings",
    "point-in-time IFRS fundamentals outside SEC Company Facts",
]


def build_audit(universe_path: str | Path) -> dict[str, object]:
    securities = load_universe(universe_path)
    by_country = Counter(
        security.listing_country or security.country or "unknown"
        for security in securities
    )
    by_pea = Counter(security.pea_eligibility_status.value for security in securities)
    dated = sum(security.universe_observation_date is not None for security in securities)
    sourced = sum(bool(security.universe_source_urls) for security in securities)
    both = sum(
        security.universe_observation_date is not None and bool(security.universe_source_urls)
        for security in securities
    )
    return {
        "schema_version": 1,
        "audited_at": datetime.now(UTC).isoformat(),
        "configured_unique_tickers": len(securities),
        "listing_countries": dict(sorted(by_country.items())),
        "pea_statuses": dict(sorted(by_pea.items())),
        "rows_with_universe_observation_date": dated,
        "rows_with_universe_source_url": sourced,
        "rows_with_complete_universe_provenance": both,
        "rows_without_complete_universe_provenance": len(securities) - both,
        "all_rows_have_complete_universe_provenance": both == len(securities),
        "literal_world_coverage_complete": False,
        "known_free_gaps": KNOWN_FREE_GAPS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default="config/universe.yaml")
    parser.add_argument("--output", default="reports/universe_coverage_latest.json")
    args = parser.parse_args()
    audit = build_audit(args.universe)
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    print(f"Audit written to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
