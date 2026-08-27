"""Validated, explicitly sourced DCF assumptions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

AssumptionPath = float | list[float]


class DcfAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    projection_years: int = Field(ge=1, le=10)
    revenue_growth: AssumptionPath
    operating_margin: AssumptionPath
    tax_rate: AssumptionPath
    depreciation_margin: AssumptionPath
    capex_margin: AssumptionPath
    working_capital_investment_margin: AssumptionPath
    wacc: float = Field(gt=0.0, le=1.0)
    terminal_growth: float = Field(ge=-0.20, le=0.20)

    @model_validator(mode="after")
    def validate_paths_and_terminal_value(self) -> "DcfAssumptions":
        ranges = {
            "revenue_growth": (-0.999999, 2.0),
            "operating_margin": (-1.0, 1.0),
            "tax_rate": (0.0, 1.0),
            "depreciation_margin": (0.0, 1.0),
            "capex_margin": (0.0, 1.0),
            "working_capital_investment_margin": (-1.0, 1.0),
        }
        for field_name, (lower, upper) in ranges.items():
            raw = getattr(self, field_name)
            values = raw if isinstance(raw, list) else [raw]
            if isinstance(raw, list) and len(raw) != self.projection_years:
                raise ValueError(
                    f"{field_name} must contain exactly projection_years values"
                )
            if any(value < lower or value > upper for value in values):
                raise ValueError(f"{field_name} falls outside [{lower}, {upper}]")
        if self.wacc <= self.terminal_growth:
            raise ValueError("wacc must be strictly greater than terminal_growth")
        return self

    def expanded(self, field_name: str) -> list[float]:
        raw: Any = getattr(self, field_name)
        return list(raw) if isinstance(raw, list) else [float(raw)] * self.projection_years


class SecurityValuationConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    assumption_date: date
    source: str = Field(min_length=1)
    notes: str | None = None
    bear: DcfAssumptions
    base: DcfAssumptions
    bull: DcfAssumptions
    normalized: DcfAssumptions | None = None


class ValuationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    securities: dict[str, SecurityValuationConfig] = Field(default_factory=dict)

    def for_ticker(self, ticker: str) -> SecurityValuationConfig | None:
        wanted = ticker.upper()
        return next(
            (config for key, config in self.securities.items() if key.upper() == wanted),
            None,
        )


def load_valuation_config(path: str | Path) -> ValuationConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return ValuationConfig.model_validate(raw)
