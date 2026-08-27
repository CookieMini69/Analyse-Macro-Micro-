"""Synthetic-only test data factories."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.data.prices import PRICE_COLUMNS


def price_frame(
    prices: list[float] | np.ndarray,
    *,
    ticker: str = "TEST",
    start: str = "2024-01-02",
    adjusted: bool = True,
) -> pd.DataFrame:
    values = np.asarray(prices, dtype=float)
    dates = pd.bdate_range(start=start, periods=len(values))
    retrieved = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    frame = pd.DataFrame(
        {
            "ticker": ticker,
            "observation_date": dates,
            "open": values,
            "high": values * 1.01,
            "low": values * 0.99,
            "close": values,
            "adjusted_close": values if adjusted else np.nan,
            "volume": np.full(len(values), 1_000_000),
            "exchange": "SYNTHETIC_TEST_ONLY",
            "currency": "USD",
            "source": "synthetic_test_fixture",
            "source_url": None,
            "retrieved_at": retrieved,
            "period": "1d",
            "unit": "USD",
            "confidence": 1.0,
            "data_status": "available",
        }
    )
    return frame[PRICE_COLUMNS]

