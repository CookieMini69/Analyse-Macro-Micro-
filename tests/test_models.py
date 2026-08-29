from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from src.models import DataStatus, FinancialMetric, ObservationMetadata, Security


def metadata(status: DataStatus) -> ObservationMetadata:
    return ObservationMetadata(
        source="test",
        source_url="https://example.invalid",
        retrieved_at=datetime.now(UTC),
        observation_date=date(2025, 12, 31),
        period="FY2025",
        currency="USD",
        unit="USD",
        confidence=1.0,
        status=status,
    )


def test_null_metric_requires_unavailable_status() -> None:
    with pytest.raises(ValidationError, match="null value"):
        FinancialMetric(name="revenue", value=None, metadata=metadata(DataStatus.AVAILABLE))


def test_unavailable_metric_preserves_null() -> None:
    metric = FinancialMetric(
        name="revenue",
        value=None,
        metadata=metadata(DataStatus.DATA_UNAVAILABLE),
    )
    assert metric.value is None
    assert metric.metadata.status == DataStatus.DATA_UNAVAILABLE


def test_confidence_must_be_bounded() -> None:
    with pytest.raises(ValidationError):
        ObservationMetadata(
            source="test",
            retrieved_at=datetime.now(UTC),
            confidence=1.2,
        )


def test_non_default_price_scale_requires_an_explanation() -> None:
    with pytest.raises(ValidationError, match="price_scale_reason"):
        Security(ticker="TEST.L", price_scale=0.01)
