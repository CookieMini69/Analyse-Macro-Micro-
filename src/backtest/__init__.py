"""Strict archived-snapshot point-in-time backtesting."""


def run_backtest(*args, **kwargs):
    """Import lazily so ``python -m src.backtest.engine`` stays warning-free."""

    from src.backtest.engine import run_backtest as implementation

    return implementation(*args, **kwargs)


__all__ = ["run_backtest"]
