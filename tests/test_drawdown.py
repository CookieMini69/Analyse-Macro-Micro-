import numpy as np
import pytest

from src.models import DataStatus
from src.screening.drawdown import calculate_price_metrics
from tests.factories import price_frame


def test_calculates_drawdowns_returns_and_moving_averages() -> None:
    prices = np.linspace(100, 200, 299).tolist() + [100.0]
    metrics = calculate_price_metrics(price_frame(prices))
    assert metrics.current_price == 100.0
    assert metrics.price_basis == "adjusted_close"
    assert metrics.values["drawdown_ath"].value == pytest.approx(-0.5)
    assert metrics.values["drawdown_52w"].value < -0.49
    assert metrics.values["drawdown_3m"].value < -0.40
    assert metrics.values["return_3m"].value < -0.40
    assert metrics.values["distance_ma200"].status == DataStatus.AVAILABLE
    assert metrics.values["rsi"].status == DataStatus.AVAILABLE


def test_discloses_close_fallback() -> None:
    metrics = calculate_price_metrics(price_frame(np.linspace(10, 20, 260), adjusted=False))
    assert metrics.price_basis == "close"
    assert metrics.current_price == pytest.approx(20.0)


def test_discloses_row_level_close_fallback_for_invalid_adjusted_value() -> None:
    frame = price_frame(np.linspace(10, 20, 260))
    frame.loc[100, "adjusted_close"] = np.nan
    metrics = calculate_price_metrics(frame)
    assert metrics.price_basis == "adjusted_close_with_close_fallback"
    assert metrics.current_price == pytest.approx(20.0)


def test_insufficient_history_returns_null_with_status() -> None:
    metrics = calculate_price_metrics(price_frame([10.0, 9.0, 8.0]))
    one_year = metrics.values["drawdown_1y"]
    assert one_year.value is None
    assert one_year.status == DataStatus.DATA_UNAVAILABLE
    assert "252" in (one_year.reason or "")


def test_trailing_drawdown_is_not_mislabeled_endpoint_return() -> None:
    prices = np.full(300, 100.0)
    prices[-40] = 150.0
    metrics = calculate_price_metrics(price_frame(prices))
    assert metrics.values["return_3m"].value == pytest.approx(0.0)
    assert metrics.values["drawdown_3m"].value == pytest.approx(-1 / 3)


def test_beta_and_relative_performance_use_aligned_benchmark() -> None:
    benchmark = np.linspace(100, 130, 300)
    asset = benchmark * np.linspace(1.0, 0.8, 300)
    metrics = calculate_price_metrics(
        price_frame(asset, ticker="ASSET"),
        benchmark_frame=price_frame(benchmark, ticker="BENCH"),
    )
    assert metrics.values["beta"].value is not None
    assert metrics.values["relative_benchmark_performance"].value < 0
    assert metrics.values["relative_sector_performance"].value is None
