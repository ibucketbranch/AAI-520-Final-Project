"""Market tool: price history and indicators such as RSI and MACD.

Fetches the numbers people read before buying, from yfinance. Serves the
"uses tools dynamically" agent function and the routing workflow's market
specialist.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import yfinance as yf

from investment_committee.models import Evidence, Run

TickerFactory = Callable[[str], Any]


class MarketDataError(RuntimeError):
    """Raised when the market source returns no usable price history."""


def _rsi(close: pd.Series, periods: int = 14) -> float | None:
    """Return the latest Wilder-style RSI when enough closes exist."""
    if len(close) <= periods:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / periods, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / periods, adjust=False).mean()
    average_gain = float(gain.iloc[-1])
    average_loss = float(loss.iloc[-1])
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    return 100 - (100 / (1 + average_gain / average_loss))


def gather_market(run: Run, ticker_factory: TickerFactory | None = None) -> list[Evidence]:
    """Collect latest close, RSI, and MACD evidence from yfinance.

    Args:
        run: Research run that owns the evidence.
        ticker_factory: Injectable replacement for ``yfinance.Ticker``.

    Returns:
        Available market facts, always including the latest close.

    Raises:
        MarketDataError: If no closing-price history is available.
    """
    make_ticker = ticker_factory or yf.Ticker
    history = make_ticker(run.symbol).history(period="6mo", interval="1d", auto_adjust=False)
    if history.empty or "Close" not in history:
        raise MarketDataError(f"No market history returned for {run.symbol}.")

    close = history["Close"].dropna()
    if close.empty:
        raise MarketDataError(f"No closing prices returned for {run.symbol}.")

    as_of = pd.Timestamp(close.index[-1]).date().isoformat()
    reference = f"yfinance:{run.symbol}:history:6mo"
    evidence = [
        Evidence(
            run_id=run.run_id,
            symbol=run.symbol,
            source="market",
            title="Latest close",
            content=f"{run.symbol} closed at ${float(close.iloc[-1]):,.2f}.",
            as_of=as_of,
            reference=reference,
        )
    ]

    rsi = _rsi(close)
    if rsi is not None:
        evidence.append(
            Evidence(
                run_id=run.run_id,
                symbol=run.symbol,
                source="market",
                title="RSI(14)",
                content=f"The 14-day RSI was {rsi:.1f}.",
                as_of=as_of,
                reference=reference,
            )
        )

    if len(close) >= 26:
        macd_line = (
            close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        )
        signal = macd_line.ewm(span=9, adjust=False).mean()
        evidence.append(
            Evidence(
                run_id=run.run_id,
                symbol=run.symbol,
                source="market",
                title="MACD(12,26,9)",
                content=(
                    f"MACD was {float(macd_line.iloc[-1]):.2f}; "
                    f"the signal line was {float(signal.iloc[-1]):.2f}."
                ),
                as_of=as_of,
                reference=reference,
            )
        )
    return evidence
