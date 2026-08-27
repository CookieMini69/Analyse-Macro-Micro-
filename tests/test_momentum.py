import numpy as np
import pytest

from src.screening.momentum import annualized_volatility, relative_strength_index


def test_rsi_for_strictly_increasing_series_is_100() -> None:
    assert relative_strength_index(np.arange(1.0, 30.0)) == 100.0


def test_volatility_is_null_for_constant_single_return_sample() -> None:
    assert annualized_volatility(np.array([10.0, 11.0])) is None


def test_volatility_is_non_negative() -> None:
    value = annualized_volatility(np.array([10.0, 11.0, 10.5, 12.0]))
    assert value is not None
    assert value >= 0

