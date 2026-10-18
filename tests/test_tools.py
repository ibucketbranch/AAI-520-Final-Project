"""Offline tests for the yfinance gatherer boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from curl_cffi.requests import exceptions as curl_errors
from yfinance.exceptions import YFDataException

from investment_committee.config import ENV_VARS, Settings
from investment_committee.models import Run
from investment_committee.tools.earnings import EarningsDataError, gather_earnings
from investment_committee.tools.market import MarketDataError, gather_market
from investment_committee.tools.news import NewsDataError, gather_news


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


def settings_with(**values):
    current = {name: None for name in ENV_VARS}
    current.update(values)
    return Settings(values=current)


def fake_get(payload, calls=None):
    """Stand-in for requests.get that records the call and returns payload."""

    def get(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        return SimpleNamespace(json=lambda: payload)

    return get


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

    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: ticker,
        search_factory=lambda symbol: pytest.fail("Search should not be called"),
    )

    assert [article.article_id for article in articles] == ["current-1", "legacy-1"]
    assert [article.published for article in articles] == ["2026-09-20", "2026-09-21"]
    assert all(article.symbol == "AAPL" for article in articles)
    assert articles[0].source == "Example Wire"


def test_news_gatherer_falls_back_to_search_headlines():
    # Search records look like this: a headline and publisher, no summary.
    search = SimpleNamespace(
        news=[
            {
                "uuid": "search-1",
                "title": "Apple ships a phone update",
                "publisher": "Example Wire",
                "providerPublishTime": int(datetime(2026, 10, 1, tzinfo=UTC).timestamp()),
                "relatedTickers": ["AAPL", "T"],
            },
            {"uuid": "other-1", "title": "Microsoft news", "relatedTickers": ["MSFT"]},
        ]
    )

    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: SimpleNamespace(news=[]),
        search_factory=lambda symbol: search,
        settings=settings_with(),
    )

    assert [article.article_id for article in articles] == ["search-1"]
    assert articles[0].body == "Apple ships a phone update"
    assert articles[0].published == "2026-10-01"


def test_news_gatherer_reports_when_yahoo_has_no_news():
    with pytest.raises(NewsDataError, match="No news found for AAPL"):
        gather_news(
            Run(symbol="AAPL"),
            ticker_factory=lambda symbol: SimpleNamespace(news=None),
            search_factory=lambda symbol: SimpleNamespace(news=[]),
            settings=settings_with(),
        )


NEWSAPI_PAYLOAD = {
    "status": "ok",
    "articles": [
        {
            "source": {"id": None, "name": "Example Wire"},
            "title": "Apple raises its dividend",
            "description": "Apple said it will raise the dividend.",
            "content": "Apple said it will raise the dividend. The board met on Tuesday. [+812 chars]",
            "url": "https://example.com/apple-dividend",
            "publishedAt": "2026-10-01T14:00:00Z",
        },
        {
            "source": {"name": "Example Desk"},
            "title": "Apple opens a new store",
            "description": "The store is in Austin.",
            "content": "Customers lined up early.",
            "url": "https://example.com/apple-store",
            "publishedAt": "2026-09-30T09:00:00Z",
        },
        {"source": {"name": "Gone"}, "title": "[Removed]", "description": "[Removed]"},
    ],
}


def test_newsapi_is_used_when_ticker_news_is_empty():
    calls = []
    ticker = SimpleNamespace(news=[], info={"shortName": "Apple Inc."})

    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: ticker,
        search_factory=lambda symbol: pytest.fail("Search should not be called"),
        settings=settings_with(NEWSAPI_KEY="test-key"),
        http_get=fake_get(NEWSAPI_PAYLOAD, calls),
    )

    assert [article.title for article in articles] == [
        "Apple raises its dividend",
        "Apple opens a new store",
    ]
    # The truncation marker is removed and the description is not repeated.
    assert articles[0].body == "Apple said it will raise the dividend. The board met on Tuesday."
    assert articles[1].body == "The store is in Austin. Customers lined up early."
    assert articles[0].source == "Example Wire"
    assert articles[0].published == "2026-10-01"
    # The key goes in a header, and the company name drops "Inc.".
    assert calls[0]["headers"] == {"X-Api-Key": "test-key"}
    assert calls[0]["params"]["q"] == '"Apple"'
    assert calls[0]["params"]["searchIn"] == "title"


def test_newsapi_searches_the_symbol_when_there_is_no_company_name():
    calls = []
    gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: SimpleNamespace(news=[]),
        settings=settings_with(NEWSAPI_KEY="test-key"),
        http_get=fake_get(NEWSAPI_PAYLOAD, calls),
    )
    assert calls[0]["params"]["q"] == '"AAPL"'


def slow_get(url, **kwargs):
    raise requests.Timeout("slow")


@pytest.mark.parametrize(
    "get",
    [
        fake_get({"status": "error", "code": "rateLimited", "message": "Too many requests"}),
        slow_get,
    ],
)
def test_newsapi_problems_fall_back_to_search(get):
    search = SimpleNamespace(news=[{"uuid": "search-1", "title": "Apple headline"}])

    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: SimpleNamespace(news=[]),
        search_factory=lambda symbol: search,
        settings=settings_with(NEWSAPI_KEY="test-key"),
        http_get=get,
    )

    assert [article.article_id for article in articles] == ["search-1"]


def test_newsapi_is_skipped_without_a_key():
    search = SimpleNamespace(news=[{"uuid": "search-1", "title": "Apple headline"}])
    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: SimpleNamespace(news=[]),
        search_factory=lambda symbol: search,
        settings=settings_with(),
        http_get=lambda url, **kwargs: pytest.fail("NewsAPI should not be called"),
    )
    assert len(articles) == 1


class BrokenTicker:
    """A ticker whose news property raises the error it is given."""

    def __init__(self, error):
        self.error = error

    @property
    def news(self):
        raise self.error


def test_yahoo_timeout_still_tries_search():
    # yfinance talks to Yahoo with curl_cffi, so this is the real error type,
    # not requests.ConnectionError.
    ticker = BrokenTicker(curl_errors.Timeout("Yahoo timed out"))
    search = SimpleNamespace(news=[{"uuid": "search-1", "title": "Apple ships a phone update"}])

    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: ticker,
        search_factory=lambda symbol: search,
        settings=settings_with(),
    )

    assert [article.article_id for article in articles] == ["search-1"]


def test_yahoo_outage_error_still_tries_search():
    # This is what yfinance raises when Yahoo answers "Will be right back".
    ticker = BrokenTicker(YFDataException("Yahoo is down"))
    search = SimpleNamespace(news=[{"uuid": "search-1", "title": "Apple ships a phone update"}])

    articles = gather_news(
        Run(symbol="AAPL"),
        ticker_factory=lambda symbol: ticker,
        search_factory=lambda symbol: search,
        settings=settings_with(),
    )

    assert [article.article_id for article in articles] == ["search-1"]


def test_every_source_down_raises_news_error():
    def broken_search(symbol):
        raise curl_errors.ConnectionError("Search is down")

    with pytest.raises(NewsDataError, match="Search failed"):
        gather_news(
            Run(symbol="AAPL"),
            ticker_factory=lambda symbol: BrokenTicker(curl_errors.Timeout("Yahoo timed out")),
            search_factory=broken_search,
            settings=settings_with(),
        )
