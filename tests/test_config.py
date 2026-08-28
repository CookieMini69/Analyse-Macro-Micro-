import os
from pathlib import Path

from src.config import load_settings


def test_default_settings_resolve_paths_from_project_root() -> None:
    settings = load_settings("config/settings.yaml")
    assert settings.project_root == Path.cwd().resolve()
    assert settings.paths.universe == Path.cwd().resolve() / "config" / "universe.yaml"
    assert settings.paths.sec_cache == Path.cwd().resolve() / "data" / "cache" / "sec"
    assert settings.paths.valuation == Path.cwd().resolve() / "config" / "valuation.yaml"
    assert settings.paths.macro == Path.cwd().resolve() / "config" / "macro.yaml"
    assert settings.paths.shock_taxonomy == (
        Path.cwd().resolve() / "config" / "shock_taxonomy.yaml"
    )
    assert settings.price.history_period == "max"
    assert settings.fundamentals.history_years == 5
    assert settings.valuation.historical_minimum_points == 3
    assert settings.macro.enabled is True
    assert settings.news.lookback_days == 30
    assert settings.shock.minimum_independent_sources == 2
    assert settings.historical.enabled is True
    assert settings.historical.minimum_drawdown == -0.15


def test_project_env_file_is_loaded_without_overriding_shell(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".env").write_text("STOCK_SCANNER_TEST_VALUE=from_file\n", encoding="utf-8")
    (tmp_path / "settings.yaml").write_text(
        """
project_root: .
paths:
  universe: universe.yaml
  raw_data: raw
  processed_data: processed
  cache: cache
  reports: reports
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("STOCK_SCANNER_TEST_VALUE", "from_shell")
    load_settings(tmp_path / "settings.yaml")
    assert os.environ["STOCK_SCANNER_TEST_VALUE"] == "from_shell"
