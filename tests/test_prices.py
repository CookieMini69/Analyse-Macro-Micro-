from pathlib import Path

import numpy as np
import pandas as pd
from yfinance.exceptions import YFInvalidPeriodError

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


def test_new_listing_falls_back_to_longest_provider_period(
    tmp_path: Path, monkeypatch
) -> None:
    class NewListing:
        history_metadata = {"currency": "USD"}

        def __init__(self) -> None:
            self.periods: list[str] = []

        def history(self, *, period: str, **kwargs):
            self.periods.append(period)
            if period == "max":
                raise YFInvalidPeriodError("NEW", "max", "1d, 5d")
            return pd.DataFrame(
                {"Close": [10.0], "Adj Close": [10.0]},
                index=pd.DatetimeIndex(["2026-08-28"]),
            )

    instrument = NewListing()
    monkeypatch.setattr("src.data.prices.yf.Ticker", lambda ticker: instrument)
    frame, metadata = YahooFinancePriceSource(tmp_path)._download_history(
        "NEW", period="max"
    )
    assert instrument.periods == ["max", "5d"]
    assert not frame.empty
    assert metadata["currency"] == "USD"


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


def test_provider_converts_london_pence_to_configured_pounds(tmp_path: Path) -> None:
    source = StubYahooSource(tmp_path, cache_ttl_hours=24, confidence=0.8)
    security = Security(
        ticker="TEST.L",
        currency="GBP",
        price_scale=0.01,
        price_scale_reason="Yahoo London quotes are expressed in GBp",
    )
    result = source.fetch(security, period="1mo")
    assert result.frame["close"].iloc[0] == 1.0
    assert result.frame["volume"].iloc[0] == 1000
    assert result.frame["currency"].iloc[0] == "GBP"


def test_provider_marks_non_positive_adjusted_close_missing_and_keeps_close(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("STOCK_SCANNER_CACHE_DIR", raising=False)
    class BadAdjustedSource(StubYahooSource):
        def _download_history(self, ticker: str, *, period: str):
            frame, metadata = super()._download_history(ticker, period=period)
            frame.loc[frame.index[10], "Adj Close"] = 0
            return frame, metadata

    result = BadAdjustedSource(tmp_path).fetch(Security(ticker="TEST.PA"), period="max")
    assert result.status == DataStatus.AVAILABLE
    assert pd.isna(result.frame.loc[10, "adjusted_close"])
    assert result.frame.loc[10, "close"] > 0


def test_provider_empty_response_is_data_unavailable(tmp_path: Path) -> None:
    class EmptySource(YahooFinancePriceSource):
        def _download_history(self, ticker: str, *, period: str):
            return pd.DataFrame(), {}

    result = EmptySource(tmp_path).fetch(Security(ticker="MISSING"))
    assert result.status == DataStatus.DATA_UNAVAILABLE
    assert result.frame.empty
    assert "data_unavailable" in (result.error or "")


def test_bulk_provider_returns_one_normalized_result_per_security(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("STOCK_SCANNER_CACHE_DIR", raising=False)
    dates = pd.bdate_range("2025-01-01", periods=260)
    columns = pd.MultiIndex.from_product(
        [["AAA", "BBB"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]],
        names=["Ticker", "Price"],
    )
    bulk = pd.DataFrame(index=dates, columns=columns, dtype=float)
    for ticker in ("AAA", "BBB"):
        bulk[(ticker, "Open")] = 10
        bulk[(ticker, "High")] = 11
        bulk[(ticker, "Low")] = 9
        bulk[(ticker, "Close")] = 10
        bulk[(ticker, "Adj Close")] = 10
        bulk[(ticker, "Volume")] = 100
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "src.data.prices.yf.download",
        lambda tickers, **kwargs: calls.append(tickers) or bulk,
    )
    source = YahooFinancePriceSource(tmp_path)
    securities = [
        Security(ticker="AAA", currency="USD"),
        Security(ticker="BBB", currency="USD"),
    ]
    results = source.fetch_many(securities)
    assert calls == [["AAA", "BBB"]]
    assert set(results) == {"AAA", "BBB"}
    assert all(result.status == DataStatus.AVAILABLE for result in results.values())
    source.fetch_many(securities)
    assert len(calls) == 1


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
