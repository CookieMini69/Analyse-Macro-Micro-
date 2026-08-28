from datetime import UTC, date, datetime

import numpy as np

from src.analysis.fundamentals import analyze_fundamentals
from src.analysis.historical import (
    analyze_historical_analogues,
    detect_drawdown_episodes,
)
from src.analysis.valuation import analyze_valuation
from src.config import HistoricalSettings, ValuationSettings
from src.data.sources import PriceHistoryResult
from src.models import DataQuality, DataStatus, Security
from tests.factories import price_frame
from tests.test_fundamental_analysis import complete_data


def episode_prices() -> np.ndarray:
    return np.concatenate(
        [
            np.full(10, 100.0),
            np.linspace(99.0, 70.0, 20),
            np.linspace(72.0, 100.0, 20),
            np.linspace(100.1, 110.0, 300),
            np.linspace(108.0, 78.0, 20),
            np.full(10, 80.0),
        ]
    )


def price_result(security: Security) -> PriceHistoryResult:
    return PriceHistoryResult(
        security=security,
        frame=price_frame(
            episode_prices(), ticker=security.ticker, start="2023-01-02"
        ),
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        source="synthetic_test_fixture",
        source_url=None,
    )


def test_detects_completed_and_active_episodes_without_overlap() -> None:
    frame = price_frame(episode_prices(), start="2023-01-02")
    completed, current = detect_drawdown_episodes(frame, minimum_drawdown=-0.15)

    assert len(completed) == 1
    assert completed[0].recovery_date is not None
    assert np.isclose(completed[0].maximum_drawdown, -0.30)
    assert current is not None
    assert current.recovery_date is None
    assert current.maximum_drawdown < -0.25
    assert completed[0].recovery_date < current.peak_date


def test_analogue_keeps_future_returns_and_sec_facts_beyond_cutoff_unavailable() -> None:
    security = Security(
        ticker="TEST", cik="1", company="Synthetic Test", country="United States",
        currency="USD",
    )
    prices = price_result(security)
    fundamental_data = complete_data()
    fundamental_data.security = security
    fundamental = analyze_fundamentals(fundamental_data)
    valuation = analyze_valuation(
        security,
        fundamental,
        prices,
        None,
        ValuationSettings(historical_minimum_points=1),
    )
    cutoff = datetime.combine(
        prices.frame["observation_date"].iloc[-1], datetime.max.time(), tzinfo=UTC
    )

    result = analyze_historical_analogues(
        security,
        prices,
        HistoricalSettings(minimum_drawdown=-0.15),
        as_of=cutoff,
        fundamental=fundamental,
        valuation=valuation,
    )

    assert result.status == DataStatus.AVAILABLE
    assert result.current_episode is not None
    assert len(result.analogues) == 1
    analogue = result.analogues[0]
    assert analogue.similarity_coverage >= 0.55
    assert analogue.episode.subsequent_returns["return_24m"].status == DataStatus.DATA_UNAVAILABLE
    current_fundamentals = result.current_episode.fundamentals
    assert current_fundamentals is not None
    assert current_fundamentals.period_end == date(2023, 12, 31)
    assert all("-24-" not in accession for accession in current_fundamentals.source_accessions)
    assert all(
        point.as_of.date() <= result.current_episode.peak_date
        for point in (
            result.current_episode.fundamentals,
            result.current_episode.valuation,
        )
        if point is not None
    )


def test_no_active_threshold_drawdown_is_explicitly_not_applicable() -> None:
    security = Security(ticker="TEST")
    prices = PriceHistoryResult(
        security=security,
        frame=price_frame(np.linspace(100.0, 120.0, 100)),
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.MEDIUM,
        source="synthetic_test_fixture",
        source_url=None,
    )
    result = analyze_historical_analogues(
        security,
        prices,
        HistoricalSettings(),
        as_of=datetime(2025, 1, 1, tzinfo=UTC),
    )
    assert result.status == DataStatus.NOT_APPLICABLE
    assert result.current_episode is None
    assert result.analogues == []


def test_standalone_analysis_defensively_excludes_future_price_bars() -> None:
    security = Security(ticker="TEST")
    frame = price_frame([100.0, 80.0, 100.0], start="2024-01-02")
    prices = PriceHistoryResult(
        security=security,
        frame=frame,
        status=DataStatus.AVAILABLE,
        data_quality=DataQuality.LOW,
        source="synthetic_test_fixture",
        source_url=None,
    )
    result = analyze_historical_analogues(
        security,
        prices,
        HistoricalSettings(),
        as_of=datetime(2024, 1, 4, 12, tzinfo=UTC),
    )
    assert result.current_episode is not None
    assert result.current_episode.recovery_date is None
    assert result.current_episode.trough_date == date(2024, 1, 3)
