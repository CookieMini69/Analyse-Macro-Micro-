"""Generate the dated native-world universe and its cryptographic lineage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.screening.world_universe import build_world_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="config/universe_world_native.csv")
    parser.add_argument("--manifest", default="config/universe_world_native.manifest.json")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    manifest = Path(args.manifest).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    frame, audit = build_world_snapshot()
    frame.to_csv(output, index=False)
    manifest.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{output}: {len(frame):,} verified native-listed equities")
    print(f"{manifest}: source hashes and coverage limitations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
