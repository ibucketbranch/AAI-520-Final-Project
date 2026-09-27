"""News tool: acquisitions and events that could move the price.

Fetches recent headlines for a symbol (source pending: yfinance news,
NewsAPI, or a Kaggle set). Feeds the prompt-chaining workflow: ingest ->
preprocess -> classify -> extract -> summarize.
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


def _published(record: Mapping[str, Any], content: Mapping[str, Any]) -> str:
    """Return an ISO date from current or legacy yfinance news fields."""
    value = content.get("pubDate") or record.get("pubDate")
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    timestamp = record.get("providerPublishTime")
    if isinstance(timestamp, int | float):
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()
    return "unknown"


def gather_news(run: Run, ticker_factory: TickerFactory | None = None) -> list[RawArticle]:
    """Fetch recent yfinance news and normalize it for Mina's news chain.

    Args:
        run: Research run whose symbol should be fetched.
        ticker_factory: Injectable replacement for ``yfinance.Ticker``.

    Returns:
        Articles that have both a title and usable body text. Empty and
        malformed provider records are skipped.
    """
    make_ticker = ticker_factory or yf.Ticker
    records = make_ticker(run.symbol).news or []
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
        if not isinstance(body, str) or not body.strip():
            continue

        provider = content.get("provider")
        source = provider.get("displayName") if isinstance(provider, Mapping) else None
        source = source or record.get("publisher") or "Yahoo Finance"
        published = _published(record, content)
        article_id = content.get("id") or record.get("uuid")
        if not isinstance(article_id, str) or not article_id:
            fingerprint = f"{run.symbol}|{published}|{title}".encode()
            article_id = hashlib.sha256(fingerprint).hexdigest()[:12]

        articles.append(
            RawArticle(
                article_id=article_id,
                symbol=run.symbol,
                source=str(source),
                published=published,
                title=title.strip(),
                body=body.strip(),
            )
        )
    return articles
