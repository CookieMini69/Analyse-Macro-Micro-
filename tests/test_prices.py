from pathlib import Path

import numpy as np
import pandas as pd

from src.data.prices import PRICE_COLUMNS, YahooFinancePriceSource, assess_price_quality, validate_price_frame
from src.models import DataQuality, DataStatus, Security


class StubYahooSource(YahooFinancePriceSource):
    def _download_history(self, ticker: str, *, period: str):
        dates = pd.bdate_range("2024-01-02", periods=260, tz="Europe/Paris")
        values = np.linspace(100.0, 80.0, len(dates))
        frame = pd.DataFrame(
            {
                "Open": values,
                "High": values + 1,
                "Low": values - 1,
                "Close": values,
                "Adj Close": values,
                "Volume": 1000,
            },
            index=dates,
        )
        return frame, {"currency": "EUR", "exchangeName": "Paris"}


def test_provider_normalizes_provenance_and_uses_cache(tmp_path: Path) -> None:
    source = StubYahooSource(tmp_path, cache_ttl_hours=24, confidence=0.8)
    first = source.fetch(Security(ticker="TEST.PA"), period="max")
    second = source.fetch(Security(ticker="TEST.PA"), period="max")
    assert first.status == DataStatus.AVAILABLE
    assert first.data_quality == DataQuality.MEDIUM
    assert list(first.frame.columns) == PRICE_COLUMNS
    assert first.frame["currency"].iloc[-1] == "EUR"
    assert first.frame["source"].iloc[-1] == "Yahoo Finance via yfinance"
    assert first.frame["confidence"].iloc[-1] == 0.8
    assert second.from_cache is True


def test_provider_empty_response_is_data_unavailable(tmp_path: Path) -> None:
    class EmptySource(YahooFinancePriceSource):
        def _download_history(self, ticker: str, *, period: str):
            return pd.DataFrame(), {}

    result = EmptySource(tmp_path).fetch(Security(ticker="MISSING"))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.frame.empty
    assert "data_unavailable" in (result.error or "")


def test_validation_rejects_non_positive_prices() -> None:
    frame = pd.DataFrame([{column: None for column in PRICE_COLUMNS}])
    frame.loc[0, "observation_date"] = "2026-01-01"
    frame.loc[0, "close"] = -1
    frame.loc[0, "adjusted_close"] = -1
    problems = validate_price_frame(frame)
    assert any("non-positive" in problem for problem in problems)


def test_short_history_is_low_quality() -> None:
    frame = pd.DataFrame({"adjusted_close": [10.0, 11.0], "close": [10.0, 11.0]})
    assert assess_price_quality(frame) == DataQuality.LOW

