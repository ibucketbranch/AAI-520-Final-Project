"""News tool: acquisitions and events that could move the price.

Fetches recent headlines for a symbol from yfinance. Feeds the
prompt-chaining workflow: ingest -> preprocess -> classify -> extract ->
summarize.

Ticker.news stopped returning articles in early October 2026 (Yahoo's
endpoint answers 404 and yfinance returns an empty list). When that
happens we fall back to yfinance Search, which still works but only gives
headlines, so the title is used as the body.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import yfinance as yf

from investment_committee.models import Run
from investment_committee.workflows.chaining import RawArticle

TickerFactory = Callable[[str], Any]
SearchFactory = Callable[[str], Any]

# How many headlines to ask Search for when Ticker.news is empty.
SEARCH_NEWS_COUNT = 10


class NewsDataError(RuntimeError):
    """Raised when Yahoo returns no usable news for the symbol."""


def _published(record: Mapping[str, Any], content: Mapping[str, Any]) -> str:
    """Return an ISO date from current or legacy yfinance news fields."""
    value = content.get("pubDate") or record.get("pubDate")
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    timestamp = record.get("providerPublishTime")
    if isinstance(timestamp, int | float):
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    return "unknown"


def _search_news(symbol: str) -> Any:
    """Ask yfinance Search for recent headlines about the symbol."""
    return yf.Search(symbol, news_count=SEARCH_NEWS_COUNT)


def _to_articles(records: list[Any], symbol: str, title_as_body: bool = False) -> list[RawArticle]:
    """Turn yfinance news records into RawArticle objects.

    Records without a title are skipped. Records without body text are
    skipped too, unless title_as_body is True (Search results have no
    summary, only the headline).
    """
    articles: list[RawArticle] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        nested = record.get("content")
        content = nested if isinstance(nested, Mapping) else record
        title = content.get("title") or record.get("title")
        body = (
            content.get("summary")
            or content.get("description")
            or record.get("summary")
            or record.get("description")
        )
        if not isinstance(title, str) or not title.strip():
            continue
        if (not isinstance(body, str) or not body.strip()) and title_as_body:
            body = title
        if not isinstance(body, str) or not body.strip():
            continue

        provider = content.get("provider")
        source = provider.get("displayName") if isinstance(provider, Mapping) else None
        source = source or record.get("publisher") or "Yahoo Finance"
        published = _published(record, content)
        article_id = content.get("id") or record.get("uuid")
        if not isinstance(article_id, str) or not article_id:
            fingerprint = f"{symbol}|{published}|{title}".encode()
            article_id = hashlib.sha256(fingerprint).hexdigest()[:12]

        articles.append(
            RawArticle(
                article_id=article_id,
                symbol=symbol,
                source=str(source),
                published=published,
                title=title.strip(),
                body=body.strip(),
            )
        )
    return articles


def gather_news(
    run: Run,
    ticker_factory: TickerFactory | None = None,
    search_factory: SearchFactory | None = None,
) -> list[RawArticle]:
    """Fetch recent yfinance news and normalize it for Mina's news chain.

    Args:
        run: Research run whose symbol should be fetched.
        ticker_factory: Injectable replacement for ``yfinance.Ticker``.
        search_factory: Injectable replacement for the Search fallback.

    Returns:
        Articles that have both a title and usable body text. Empty and
        malformed provider records are skipped.

    Raises:
        NewsDataError: If neither Ticker.news nor Search returns any
            usable article.
    """
    make_ticker = ticker_factory or yf.Ticker
    articles = _to_articles(make_ticker(run.symbol).news or [], run.symbol)
    if articles:
        return articles

    # Ticker.news came back empty, so try Search. Search can also return
    # stories about other companies, so keep only the ones tagged with
    # this symbol (or untagged ones).
    search = search_factory or _search_news
    records: list[Any] = []
    for record in search(run.symbol).news or []:
        if not isinstance(record, Mapping):
            continue
        related = record.get("relatedTickers")
        if isinstance(related, list) and related and run.symbol not in related:
            continue
        records.append(record)
    articles = _to_articles(records, run.symbol, title_as_body=True)
    if not articles:
        raise NewsDataError(f"Yahoo returned no news for {run.symbol}.")
    return articles
