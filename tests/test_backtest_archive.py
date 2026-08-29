from datetime import UTC, datetime

import pandas as pd
import pytest

from src.backtest.archive import archive_live_run
from src.backtest.historical_data import load_backtest_inputs
from src.models import DataQuality, OpportunityCandidate, Security


def test_live_run_is_archived_with_verifiable_signal_hash(tmp_path) -> None:
    now = datetime(2026, 8, 29, 12, tzinfo=UTC)
    result = OpportunityCandidate(
        ticker="TEST",
        opportunity_score=75.0,
        data_quality=DataQuality.HIGH,
        decline_severity_score=50.0,
        is_candidate=True,
        retrieved_at=now,
    )
    security = Security(ticker="TEST", benchmark="^GSPC")
    outputs = archive_live_run(
        [result], [security], as_of=now, archive_root=tmp_path, archived_at=now
    )
    assert len(outputs) == 3
    signal = pd.read_csv(outputs[2]).iloc[0]
    assert signal["source_archive_sha256"][:12] in outputs[1].name
    assert signal["benchmark_ticker"] == "^GSPC"
    assert bool(signal["point_in_time_validated"]) is True
    prices_path = tmp_path / "prices.csv"
    pd.DataFrame(
        [{"ticker": "TEST", "observation_date": "2026-08-29", "adjusted_close": 1}]
    ).to_csv(prices_path, index=False)
    loaded, _, _ = load_backtest_inputs(outputs[2].parent, prices_path, outputs[0].parent)
    assert bool(loaded.iloc[0]["archive_integrity_verified"]) is True


def test_historical_reconstruction_is_not_mislabeled_as_live_archive(tmp_path) -> None:
    outputs = archive_live_run(
        [],
        [],
        as_of=datetime(2020, 1, 1, tzinfo=UTC),
        archive_root=tmp_path,
        archived_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert outputs == []
    assert list(tmp_path.iterdir()) == []


def test_dated_universe_snapshot_is_write_once(tmp_path) -> None:
    now = datetime(2026, 8, 29, 12, tzinfo=UTC)
    archive_live_run(
        [], [Security(ticker="ONE")], as_of=now, archive_root=tmp_path,
        archived_at=now,
    )
    with pytest.raises(ValueError, match="different membership"):
        archive_live_run(
            [], [Security(ticker="TWO")], as_of=now, archive_root=tmp_path,
            archived_at=now,
        )


def test_loader_detects_tampered_source_archive(tmp_path) -> None:
    now = datetime(2026, 8, 29, 12, tzinfo=UTC)
    result = OpportunityCandidate(
        ticker="TEST", opportunity_score=70.0, data_quality=DataQuality.HIGH,
        decline_severity_score=40.0, is_candidate=True, retrieved_at=now,
    )
    outputs = archive_live_run(
        [result], [Security(ticker="TEST", benchmark="^GSPC")],
        as_of=now, archive_root=tmp_path, archived_at=now,
    )
    outputs[1].write_text("tampered", encoding="utf-8")
    prices_path = tmp_path / "prices.csv"
    pd.DataFrame(
        [{"ticker": "TEST", "observation_date": "2026-08-29", "adjusted_close": 1}]
    ).to_csv(prices_path, index=False)
    loaded, _, _ = load_backtest_inputs(outputs[2].parent, prices_path, outputs[0].parent)
    assert bool(loaded.iloc[0]["archive_integrity_verified"]) is False
