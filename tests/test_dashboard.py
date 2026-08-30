import json
import os
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from dashboard.data import (
    filter_scan,
    index_choices,
    latest_scan_report,
    load_latest_fundamental,
    load_price_history,
    load_scan_report,
    scenario_rows,
)


def test_latest_scan_report_and_json_decoding(tmp_path: Path) -> None:
    older = tmp_path / "stock_opportunity_scan_20260101T000000Z.csv"
    newer = tmp_path / "stock_opportunity_scan_20260102T000000Z.csv"
    row = {
        "ticker": "AAA", "listing_country": "France", "sector": "Industrials",
        "index_memberships": "CAC 40", "candidate_reasons": json.dumps(["drawdown"]),
        "scenario_metrics": json.dumps({"cases": {}}), "is_candidate": True,
        "drawdown_52w": -0.25,
    }
    pd.DataFrame([row]).to_csv(older, index=False)
    pd.DataFrame([row]).to_csv(newer, index=False)
    incomplete = tmp_path / "stock_opportunity_scan_20260103T000000Z.csv"
    incomplete.write_text("ticker,is_candidate,drawdown_52w\n", encoding="utf-8")
    # Selection is based on real modification time, not on a filename guess.
    older.touch()
    newer.touch()
    os.utime(incomplete, (newer.stat().st_mtime + 1, newer.stat().st_mtime + 1))
    assert latest_scan_report(tmp_path) == newer
    loaded = load_scan_report(newer)
    assert loaded.loc[0, "candidate_reasons"] == ["drawdown"]
    assert loaded.loc[0, "scenario_metrics"] == {"cases": {}}


def test_filters_country_index_scores_drawdown_and_risk() -> None:
    frame = pd.DataFrame([
        {"ticker": "AAA", "listing_country": "France", "sector": "Industrials", "index_memberships": "CAC 40;AEX 25", "opportunity_score": 70, "drawdown_52w": -0.30, "market_cap_eur": 2e9, "shock_nature": "temporary", "risk_score": 60},
        {"ticker": "BBB", "listing_country": "Germany", "sector": "Technology", "index_memberships": "DAX 40", "opportunity_score": 40, "drawdown_52w": -0.10, "market_cap_eur": 4e9, "shock_nature": None, "risk_score": 20},
    ])
    result = filter_scan(
        frame, countries=["France"], indices=["AEX 25"], minimum_score=60,
        maximum_drawdown=-0.20, minimum_market_cap_eur=1e9,
        shock_natures=["temporary"], minimum_risk_score=50,
    )
    assert result["ticker"].tolist() == ["AAA"]
    assert index_choices(frame) == ["AEX 25", "CAC 40", "DAX 40"]
    assert filter_scan(frame, query="alpha", candidates_only=False).empty
    searchable = frame.assign(company=["Alpha", "Beta"], is_candidate=[True, False])
    assert filter_scan(searchable, query="alpha", candidates_only=True)["ticker"].tolist() == ["AAA"]


def test_price_fundamental_and_scenario_artifacts(tmp_path: Path) -> None:
    pd.DataFrame({
        "observation_date": pd.date_range("2025-01-01", periods=80),
        "adjusted_close": range(1, 81),
    }).to_csv(tmp_path / "ABC.PA.csv", index=False)
    loaded_prices = load_price_history("ABC.PA", tmp_path)
    assert {"ma50", "ma200", "drawdown"} <= set(loaded_prices)
    fundamental = tmp_path / "ABC.PA__asof_20260101T000000Z__retrieved_20260101T010000Z.json"
    fundamental.write_text(json.dumps({"ticker": "ABC.PA", "annual_observations": {}}), encoding="utf-8")
    assert load_latest_fundamental("ABC.PA", tmp_path)["ticker"] == "ABC.PA"
    rows = scenario_rows({
        "cases": {"base": {"horizons": [{"months": 12, "target_price": {"value": 123, "status": "available"}}], "assumption_coverage": 0.8}}
    }, 12)
    assert rows[0]["Objectif"] == 123


def test_streamlit_dashboard_renders_without_exception() -> None:
    app = AppTest.from_file("dashboard/app.py", default_timeout=30).run()
    assert not app.exception
    assert [title.value for title in app.title] == ["AI Stock Opportunity Scanner"]
    assert len(app.multiselect) == 5
    assert any(button.label == "Réinitialiser tous les filtres" for button in app.button)
    assert len(app.tabs) == 7

