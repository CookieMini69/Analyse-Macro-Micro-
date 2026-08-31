import json
from pathlib import Path

import pandas as pd

from src.screening.world_universe import parse_nse


def test_nse_parser_keeps_only_equity_series() -> None:
    content = (
        "SYMBOL,NAME OF COMPANY,SERIES,ISIN NUMBER\n"
        "ALPHA,Alpha Limited,EQ,INE000000001\n"
        "BETA,Beta Preference,BE,INE000000002\n"
    ).encode()
    frame, _ = parse_nse(content)
    assert frame[["ticker", "company"]].to_dict("records") == [
        {"ticker": "ALPHA.NS", "company": "Alpha Limited"}
    ]


def test_committed_native_snapshot_matches_cryptographic_manifest() -> None:
    snapshot = pd.read_csv(Path("config/universe_world_native.csv"))
    manifest = json.loads(
        Path("config/universe_world_native.manifest.json").read_text(encoding="utf-8")
    )
    assert len(snapshot) == manifest["rows"] == 10_752
    assert {item["source"] for item in manifest["sources"]} == {
        "jpx", "nse", "asx", "hkex",
    }
    assert sum(item["equity_rows"] for item in manifest["sources"]) == len(snapshot)
    assert all(len(item["sha256"]) == 64 for item in manifest["sources"])
    assert manifest["world_complete"] is False
