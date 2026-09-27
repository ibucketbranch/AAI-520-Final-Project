"""Earnings tool: last quarter results for a symbol.

Fetches recent earnings figures (yfinance to start). Serves the "uses tools
dynamically" agent function and the routing workflow's earnings specialist.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import yfinance as yf

from investment_committee.models import Evidence, Run

TickerFactory = Callable[[str], Any]


class EarningsDataError(RuntimeError):
    """Raised when the earnings source has no supported quarterly fields."""


def _row_value(statement: pd.DataFrame, column: Any, names: tuple[str, ...]) -> float | None:
    """Return the first non-null value among alternative row names."""
    for name in names:
        if name in statement.index:
            value = statement.at[name, column]
            if not pd.isna(value):
                return float(value)
    return None


def _dollars(value: float) -> str:
    """Format a signed dollar amount with the sign before the symbol."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _money(value: float) -> str:
    """Format a dollar amount using a readable scale."""
    magnitude = abs(value)
    for scale, label in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
        if magnitude >= scale:
            return f"{_dollars(value / scale)} {label}"
    return _dollars(value)


def gather_earnings(run: Run, ticker_factory: TickerFactory | None = None) -> list[Evidence]:
    """Collect the latest quarterly revenue, income, and EPS when available.

    Args:
        run: Research run that owns the evidence.
        ticker_factory: Injectable replacement for ``yfinance.Ticker``.

    Returns:
        One evidence item for each supported field present in the statement.

    Raises:
        EarningsDataError: If no quarterly statement or supported field is
            available.
    """
    make_ticker = ticker_factory or yf.Ticker
    statement = make_ticker(run.symbol).quarterly_income_stmt
    if statement.empty or not len(statement.columns):
        raise EarningsDataError(f"No quarterly income statement returned for {run.symbol}.")

    latest_column = max(statement.columns, key=pd.Timestamp)
    as_of = pd.Timestamp(latest_column).date().isoformat()
    reference = f"yfinance:{run.symbol}:quarterly_income_stmt"
    fields = (
        ("Quarterly revenue", ("Total Revenue", "Operating Revenue"), "money"),
        ("Quarterly net income", ("Net Income", "Net Income Common Stockholders"), "money"),
        ("Diluted EPS", ("Diluted EPS",), "eps"),
    )

    evidence: list[Evidence] = []
    for title, row_names, value_type in fields:
        value = _row_value(statement, latest_column, row_names)
        if value is None:
            continue
        displayed = _money(value) if value_type == "money" else f"{_dollars(value)} per share"
        evidence.append(
            Evidence(
                run_id=run.run_id,
                symbol=run.symbol,
                source="earnings",
                title=title,
                content=f"{title} was {displayed} for the quarter ended {as_of}.",
                as_of=as_of,
                reference=reference,
            )
        )

    if not evidence:
        raise EarningsDataError(f"No supported earnings fields returned for {run.symbol}.")
    return evidence
