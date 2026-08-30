"""Deterministic, local-first opportunity alerts with durable deduplication."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from src.config import AlertSettings
from src.models import OpportunityAlert, OpportunityCandidate, PeaEligibilityStatus


class AlertSink(Protocol):
    """Delivery boundary for later email, Telegram, or Discord adapters."""

    def deliver(self, alerts: list[OpportunityAlert]) -> list[Path]: ...


def _alert_id(candidate: OpportunityCandidate) -> str:
    identity = (
        f"{candidate.ticker.upper()}|{candidate.observation_date.isoformat()}|"
        f"{candidate.opportunity_score:.6f}|opportunity-scoring-v1"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def build_alerts(
    candidates: list[OpportunityCandidate],
    settings: AlertSettings,
    *,
    generated_at: datetime | None = None,
) -> list[OpportunityAlert]:
    """Select threshold-qualified alerts without imputing a missing score."""

    if not settings.enabled:
        return []
    now = generated_at or datetime.now(UTC)
    accepted_pea = {
        PeaEligibilityStatus.CONFIRMED_ELIGIBLE,
        PeaEligibilityStatus.REVIEW_REQUIRED,
    }
    alerts: list[OpportunityAlert] = []
    for item in candidates:
        if not item.is_candidate or item.observation_date is None:
            continue
        if item.opportunity_score is None or item.opportunity_score_coverage is None:
            continue
        if item.opportunity_score < settings.minimum_opportunity_score:
            continue
        if item.opportunity_score_coverage < settings.minimum_score_coverage:
            continue
        if settings.require_pea_focus and item.pea_eligibility_status not in accepted_pea:
            continue
        alerts.append(
            OpportunityAlert(
                alert_id=_alert_id(item),
                ticker=item.ticker,
                company=item.company,
                generated_at=now,
                observation_date=item.observation_date,
                pea_eligibility_status=item.pea_eligibility_status,
                opportunity_score=item.opportunity_score,
                opportunity_score_coverage=item.opportunity_score_coverage,
                drawdown_52w=item.drawdown_52w,
                temporary_shock_score=item.temporary_shock_score,
                upside_base=item.upside_base,
                risk_reward=item.risk_reward,
                candidate_reasons=item.candidate_reasons,
                score_band=item.score_band,
                source_count=len(item.sources),
            )
        )
    return sorted(alerts, key=lambda alert: alert.opportunity_score, reverse=True)


def _load_delivered_ids(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"alert state is unreadable: {state_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(
        payload.get("delivered_alert_ids", []), list
    ):
        raise ValueError(f"alert state has an invalid schema: {state_path}")
    return {str(value) for value in payload.get("delivered_alert_ids", [])}


def persist_local_alerts(
    alerts: list[OpportunityAlert],
    output_dir: str | Path,
    state_path: str | Path,
    *,
    send_only_new: bool = True,
) -> tuple[list[OpportunityAlert], list[Path]]:
    """Write immutable JSON/CSV/Markdown artifacts and atomically update state."""

    destination = Path(output_dir)
    state = Path(state_path)
    delivered = _load_delivered_ids(state) if send_only_new else set()
    selected = [alert for alert in alerts if alert.alert_id not in delivered]
    if not selected:
        return [], []

    destination.mkdir(parents=True, exist_ok=True)
    timestamp = selected[0].generated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    stem = destination / f"opportunity_alerts_{timestamp}"
    json_path = stem.with_suffix(".json")
    csv_path = stem.with_suffix(".csv")
    markdown_path = stem.with_suffix(".md")
    json_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in selected], indent=2),
        encoding="utf-8",
    )
    pd.DataFrame([item.model_dump(mode="json") for item in selected]).to_csv(
        csv_path, index=False
    )
    lines = ["# Nouvelles opportunités à vérifier", ""]
    for item in selected:
        drawdown = "indisponible" if item.drawdown_52w is None else f"{item.drawdown_52w:.1%}"
        lines.extend(
            [
                f"## {item.ticker} — {item.company or 'Société non renseignée'}",
                "",
                f"- Score : {item.opportunity_score:.1f}/100 "
                f"(couverture {item.opportunity_score_coverage:.0%})",
                f"- Drawdown 52 semaines : {drawdown}",
                f"- Statut PEA : {item.pea_eligibility_status.value}",
                f"- Raisons techniques : {', '.join(item.candidate_reasons) or 'non renseignées'}",
                f"- {item.disclaimer}",
                "",
            ]
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    known = delivered | {item.alert_id for item in selected}
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = state.with_suffix(state.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "delivered_alert_ids": sorted(known),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(state)
    return selected, [json_path, csv_path, markdown_path]

