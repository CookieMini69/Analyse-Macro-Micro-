from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.models import Security


def test_market_cap_requires_complete_provenance() -> None:
    with pytest.raises(ValidationError, match="market_cap requires provenance"):
        Security(ticker="TEST", market_cap=1_000_000)


def test_market_cap_with_provenance_is_accepted() -> None:
    security = Security(
        ticker="TEST",
        market_cap=1_000_000,
        market_cap_currency="EUR",
        market_cap_source="Test source",
        market_cap_source_url="https://example.invalid/test",
        market_cap_observation_date=date(2026, 1, 1),
        market_cap_retrieved_at=datetime(2026, 1, 2, tzinfo=UTC),
        market_cap_confidence=1.0,
    )
    assert security.market_cap == 1_000_000


def test_numeric_cik_is_normalized_to_string() -> None:
    assert Security(ticker="TEST", cik=320193).cik == "320193"
    with pytest.raises(ValidationError):
        Security(ticker="TEST", cik=320193.5)
