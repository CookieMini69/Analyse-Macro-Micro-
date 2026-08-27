"""Validated macro-series, exposure, and shock-taxonomy configuration."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models import ShockCategory


class MacroSeriesDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    series_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool = True


class MacroConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    series: dict[str, MacroSeriesDefinition] = Field(default_factory=dict)


class MacroExposureDefinition(BaseModel):
    """A documented sensitivity hypothesis, never an inferred causal effect."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    series_key: str = Field(min_length=1)
    coefficient: float = Field(ge=-10.0, le=10.0)
    rationale: str = Field(min_length=1)
    assumption_date: date
    source: str = Field(min_length=1)

    @field_validator("coefficient")
    @classmethod
    def coefficient_cannot_be_zero(cls, value: float) -> float:
        if value == 0:
            raise ValueError("exposure coefficient cannot be zero")
        return value


class MacroExposureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    sector_exposures: dict[str, list[MacroExposureDefinition]] = Field(
        default_factory=dict
    )
    security_exposures: dict[str, list[MacroExposureDefinition]] = Field(
        default_factory=dict
    )

    def for_security(
        self, ticker: str, sector: str | None
    ) -> list[MacroExposureDefinition]:
        selected_groups: list[list[MacroExposureDefinition]] = []
        if sector:
            selected_groups.extend(
                exposures
                for key, exposures in self.sector_exposures.items()
                if key.casefold() == sector.casefold()
            )
        selected_groups.extend(
            exposures
            for key, exposures in self.security_exposures.items()
            if key.upper() == ticker.upper()
        )
        flattened = [item for group in selected_groups for item in group]
        by_series = {item.series_key: item for item in flattened}
        return list(by_series.values())


class ShockTaxonomyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    categories: dict[str, list[str]] = Field(default_factory=dict)
    temporary_terms: list[str] = Field(default_factory=list)
    resolution_terms: list[str] = Field(default_factory=list)
    damage_terms: list[str] = Field(default_factory=list)
    structural_terms: list[str] = Field(default_factory=list)
    severe_structural_terms: list[str] = Field(default_factory=list)

    @field_validator("categories")
    @classmethod
    def categories_must_match_the_public_taxonomy(
        cls, value: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        allowed = {category.value for category in ShockCategory}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown shock categories: {', '.join(unknown)}")
        empty = sorted(key for key, terms in value.items() if not terms)
        if empty:
            raise ValueError(f"shock categories without terms: {', '.join(empty)}")
        return value


def load_macro_config(path: str | Path) -> MacroConfig:
    return MacroConfig.model_validate(_load_yaml(path))


def load_macro_exposure_config(path: str | Path) -> MacroExposureConfig:
    return MacroExposureConfig.model_validate(_load_yaml(path))


def load_shock_taxonomy(path: str | Path) -> ShockTaxonomyConfig:
    return ShockTaxonomyConfig.model_validate(_load_yaml(path))


def _load_yaml(path: str | Path) -> dict:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
