"""Offline tests for the yfinance gatherer boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from investment_committee.models import Run
from investment_committee.tools.earnings import EarningsDataError, gather_earnings
from investment_committee.tools.market import MarketDataError, gather_market
from investment_committee.tools.news import gather_news


def test_market_gatherer_builds_close_rsi_and_macd_evidence():
    dates = pd.date_range("2026-07-01", periods=40, freq="D")
    history = pd.DataFrame({"Close": [100.0 + value for value in range(40)]}, index=dates)
    ticker = SimpleNamespace(history=lambda **_kwargs: history)
    run = Run(run_id="r1", symbol="AAPL")

    evidence = gather_market(run, ticker_factory=lambda symbol: ticker)

    assert {item.title for item in evidence} == {"Latest close", "RSI(14)", "MACD(12,26,9)"}
    assert all(item.run_id == "r1" and item.source == "market" for item in evidence)
    assert all(item.as_of == "2026-08-09" for item in evidence)
    assert "$139.00" in evidence[0].content


def test_market_gatherer_rejects_empty_history():
    ticker = SimpleNamespace(history=lambda **_kwargs: pd.DataFrame())
    with pytest.raises(MarketDataError):
        gather_market(Run(symbol="AAPL"), ticker_factory=lambda symbol: ticker)


def test_earnings_gatherer_uses_latest_quarter_and_known_rows():
    latest = pd.Timestamp("2026-06-30")
    earlier = pd.Timestamp("2026-03-31")
    statement = pd.DataFrame(
        {
            latest: [91.2e9, 24.0e9, 1.42],
            earlier: [88.0e9, 22.0e9, 1.31],
        },
        index=["Total Revenue", "Net Income", "Diluted EPS"],
    )
    ticker = SimpleNamespace(quarterly_income_stmt=statement)
    run = Run(run_id="r1", symbol="AAPL")

    evidence = gather_earnings(run, ticker_factory=lambda symbol: ticker)

    assert [item.title for item in evidence] == [
        "Quarterly revenue",
        "Quarterly net income",
        "Diluted EPS",
    ]
    assert all(item.as_of == "2026-06-30" and item.source == "earnings" for item in evidence)
    assert "$91.20 billion" in evidence[0].content
    assert "$1.42 per share" in evidence[2].content


def test_earnings_gatherer_rejects_unknown_statement_rows():
    statement = pd.DataFrame(
        {pd.Timestamp("2026-06-30"): [1.0]},
        index=["Unrelated Row"],
    )
    ticker = SimpleNamespace(quarterly_income_stmt=statement)
    with pytest.raises(EarningsDataError):
        gather_earnings(Run(symbol="AAPL"), ticker_factory=lambda symbol: ticker)


def test_earnings_gatherer_formats_losses_with_the_sign_before_dollars():
    statement = pd.DataFrame(
        {pd.Timestamp("2026-06-30"): [-500_000.0, -1.2e6, -0.5]},
        index=["Total Revenue", "Net Income", "Diluted EPS"],
    )
    ticker = SimpleNamespace(quarterly_income_stmt=statement)

    evidence = gather_earnings(
        Run(symbol="LOSS"),
        ticker_factory=lambda symbol: ticker,
    )

    assert "-$500,000.00" in evidence[0].content
    assert "-$1.20 million" in evidence[1].content
    assert "-$0.50 per share" in evidence[2].content


def test_news_gatherer_normalizes_current_and_legacy_records():
    timestamp = int(datetime(2026, 9, 21, tzinfo=UTC).timestamp())
    records = [
        {
            "content": {
                "id": "current-1",
                "title": "Apple reports quarterly results",
                "summary": "Revenue increased during the quarter.",
                "pubDate": "2026-09-20T12:00:00Z",
                "provider": {"displayName": "Example Wire"},
            }
        },
        {
            "uuid": "legacy-1",
            "title": "Apple announces a product update",
            "summary": "The update is planned for October.",
            "publisher": "Example Desk",
            "providerPublishTime": timestamp,
        },
        {"title": "Missing body"},
    ]
    ticker = SimpleNamespace(news=records)

    articles = gather_news(Run(symbol="AAPL"), ticker_factory=lambda symbol: ticker)

    assert [article.article_id for article in articles] == ["current-1", "legacy-1"]
    assert [article.published for article in articles] == ["2026-09-20", "2026-09-21"]
    assert all(article.symbol == "AAPL" for article in articles)
    assert articles[0].source == "Example Wire"
