"""Large-decline detection and a deliberately non-investment V1 ranking score."""

from __future__ import annotations

from src.config import ScreeningSettings
from src.models import MetricValue


def candidate_reasons(
    metrics: dict[str, MetricValue], settings: ScreeningSettings
) -> list[str]:
    thresholds = {
        "drawdown_52w": settings.drawdown_52w_threshold,
        "drawdown_3m": settings.drawdown_3m_threshold,
        "drawdown_6m": settings.drawdown_6m_threshold,
        "relative_sector_performance": settings.relative_sector_threshold,
    }
    reasons: list[str] = []
    for name, threshold in thresholds.items():
        metric = metrics[name]
        if metric.value is not None and metric.value <= threshold:
            reasons.append(f"{name}={metric.value:.2%} <= {threshold:.2%}")
    return reasons


def decline_severity_score(metrics: dict[str, MetricValue]) -> float:
    """Score observed decline severity only; this is not an opportunity score.

    Missing metrics contribute zero rather than being silently imputed. Each
    component reaches its cap at a documented decline magnitude.
    """

    components = (
        ("drawdown_52w", 40.0, 0.50),
        ("drawdown_3m", 25.0, 0.30),
        ("drawdown_6m", 20.0, 0.40),
        ("relative_sector_performance", 15.0, 0.30),
    )
    score = 0.0
    for name, weight, cap in components:
        value = metrics[name].value
        if value is not None and value < 0:
            score += weight * min(abs(value) / cap, 1.0)
    return round(min(score, 100.0), 2)

