"""Risk-resilience score: a higher value means lower measured risk."""

from __future__ import annotations

from src.models import (
    DataStatus,
    EvidenceScore,
    FundamentalAnalysisResult,
    ScenarioAnalysisResult,
    ScoreComponent,
    ShockAnalysisResult,
    ShockNature,
)
from src.scoring.confidence import build_evidence_score, piecewise_score


def score_risk_resilience(
    fundamental: FundamentalAnalysisResult | None,
    scenario: ScenarioAnalysisResult | None,
    shock: ShockAnalysisResult | None,
    *,
    volatility: float | None,
    beta: float | None,
    minimum_coverage: float,
) -> EvidenceScore:
    balance = None
    if fundamental is not None:
        component = fundamental.quality_score.components.get("balance_sheet")
        balance = component.adjusted_score if component is not None else None

    bear_downside = (
        scenario.risk_reward.downside_bear.value if scenario is not None else None
    )
    nature_scores = {
        ShockNature.TEMPORARY: 90.0,
        ShockNature.PROBABLY_TEMPORARY: 80.0,
        ShockNature.UNCERTAIN: 50.0,
        ShockNature.STRUCTURAL: 20.0,
        ShockNature.SEVERE_STRUCTURAL: 0.0,
    }
    nature = (
        nature_scores.get(shock.nature)
        if shock is not None and shock.status == DataStatus.AVAILABLE
        else None
    )
    components = {
        "balance_sheet_resilience": _component(
            "balance_sheet_resilience", balance, 0.35,
            "Fundamental Quality balance-sheet component",
            {"balance_sheet_score": balance},
        ),
        "bear_case_protection": _component(
            "bear_case_protection",
            piecewise_score(
                bear_downside,
                ((-0.60, 0), (-0.35, 20), (-0.20, 45), (0.0, 75), (0.25, 100)),
            ) if bear_downside is not None else None,
            0.25,
            "Phase 7 bear target versus current price",
            {"bear_return": bear_downside},
        ),
        "volatility_resilience": _component(
            "volatility_resilience",
            piecewise_score(
                volatility, ((0.10, 100), (0.25, 75), (0.40, 50), (0.70, 0))
            ) if volatility is not None and volatility >= 0 else None,
            0.20,
            "point-in-time annualized price volatility",
            {"volatility": volatility},
        ),
        "beta_resilience": _component(
            "beta_resilience",
            piecewise_score(
                abs(beta), ((0.50, 100), (1.0, 75), (1.50, 40), (2.50, 0))
            ) if beta is not None else None,
            0.10,
            "point-in-time benchmark beta",
            {"beta": beta},
        ),
        "structural_shock_resilience": _component(
            "structural_shock_resilience", nature, 0.10,
            "conservative shock classification",
            {"shock_nature": shock.nature.value if shock is not None else None},
        ),
    }
    return build_evidence_score(
        "risk_resilience",
        components,
        minimum_coverage=minimum_coverage,
        methodology_version="risk-resilience-v1",
    )


def _component(
    name: str,
    score: float | None,
    weight: float,
    source: str,
    evidence: dict[str, object],
) -> ScoreComponent:
    return ScoreComponent(
        name=name,
        score=round(score, 4) if score is not None else None,
        weight=weight,
        observed=score is not None,
        source=source,
        evidence=evidence,
        reason=None if score is not None else f"{name} evidence is unavailable",
    )


__all__ = ["score_risk_resilience"]
