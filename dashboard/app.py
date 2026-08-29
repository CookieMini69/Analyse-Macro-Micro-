"""Explicit boundary for the future Phase 11 Streamlit dashboard."""

from __future__ import annotations

MESSAGE = """The Streamlit dashboard is planned for Phase 11 and is not implemented in v0.9.0.
Run `python -m src.pipeline`, then open the newest workbook in `reports/`.
This guard prevents a placeholder from being mistaken for a working interface."""


def main() -> int:
    print(MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
