from datetime import UTC, datetime

import numpy as np

from src.config import ScreeningSettings
from src.data.sources import PriceHistoryResult
from src.models import DataQuality, DataStatus, Security
from src.screening.scanner import build_scan_result, rank_results
from tests.factories import price_frame


def result(ticker: str, prices: np.ndarray) -> PriceHistoryResult:
    security = Security(ticker=ticker, company=ticker, country="France", currency="EUR")
    return PriceHistoryResult(
        security=security,
        frame=price_frame(prices, ticker=ticker),
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        source="synthetic_test_fixture",
        source_url=None,
    )


def test_builds_candidate_without_calling_it_an_opportunity_score() -> None:
    prices = np.concatenate([np.linspace(100, 150, 250), np.linspace(150, 80, 50)])
    scan = build_scan_result(result("FALL", prices), ScreeningSettings())
    assert scan.is_candidate is True
    assert scan.decline_severity_score > 0
    assert scan.data_quality in {DataQuality.MEDIUM, DataQuality.LOW}
    assert scan.current_price == 80.0


def test_rank_is_assigned_only_to_candidates() -> None:
    falling = build_scan_result(
        result("FALL", np.concatenate([np.full(250, 100.0), np.linspace(100, 60, 50)])),
        ScreeningSettings(),
    )
    flat = build_scan_result(result("FLAT", np.full(300, 100.0)), ScreeningSettings())
    ranked = rank_results([flat, falling])
    assert ranked[0].ticker == "FALL"
    assert ranked[0].rank == 1
    assert ranked[1].rank is None


def test_invalid_source_data_cannot_be_a_candidate() -> None:
    invalid = result(
        "INVALID",
        np.concatenate([np.full(250, 100.0), np.linspace(100, 60, 50)]),
    )
    invalid.status = DataStatus.INVALID
    scan = build_scan_result(invalid, ScreeningSettings())
    assert scan.candidate_reasons
    assert scan.is_candidate is False
