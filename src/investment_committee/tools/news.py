"""News tool: acquisitions and events that could move the price.

Fetches recent headlines for a symbol from yfinance. Feeds the
prompt-chaining workflow: ingest -> preprocess -> classify -> extract ->
summarize.

Ticker.news stopped returning articles in early October 2026 (Yahoo's
endpoint answers 404 and yfinance returns an empty list). So the sources
are tried in this order, and the first one with articles wins:

1. yfinance Ticker.news (summary text, free, currently broken)
2. NewsAPI, only when NEWSAPI_KEY is set (description plus a content snippet)
3. yfinance Search (headlines only, so the title is used as the body)
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import requests
import yfinance as yf
from yfinance.exceptions import YFException

from investment_committee.config import Settings, load_settings
from investment_committee.models import Run
from investment_committee.workflows.chaining import RawArticle

TickerFactory = Callable[[str], Any]
SearchFactory = Callable[[str], Any]
HttpGet = Callable[..., Any]

# How many headlines to ask Search for when Ticker.news is empty.
SEARCH_NEWS_COUNT = 10

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_PAGE_SIZE = 10
NEWSAPI_TIMEOUT = 15

# Words dropped from the end of a company name before searching NewsAPI,
# so "NVIDIA Corporation" is searched as "NVIDIA".
NAME_SUFFIXES = ["inc", "corporation", "corp", "co", "ltd", "plc"]

# NewsAPI cuts content off and ends it with a marker like "[+1234 chars]".
TRUNCATED_MARKER = re.compile(r"\s*\[\+\d+ chars\]\s*$")


# yfinance reaches Yahoo through curl_cffi, not requests. Both libraries'
# errors are OSError subclasses, yfinance raises its own YFException family
# for outages and rate limits, and a bad JSON body is a ValueError. These are
# the "the provider is having trouble" errors a source boundary should absorb.
PROVIDER_ERRORS = (OSError, YFException, ValueError)


class NewsDataError(RuntimeError):
    """Raised when no news source returns usable articles for the symbol."""


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


def _company_name(ticker: Any, symbol: str) -> str | None:
    """Return a short company name for the NewsAPI search, if yfinance has one."""
    # yfinance can fail here in many ways. The name is only a better search
    # term, so if anything goes wrong we just search for the symbol.
    try:
        name = ticker.info.get("shortName")
    except Exception:
        return None
    if not isinstance(name, str):
        return None

    words = name.replace(",", "").split()
    while len(words) > 1 and words[-1].lower().rstrip(".") in NAME_SUFFIXES:
        words.pop()
    short_name = " ".join(words)
    if short_name.upper() == symbol:
        return None
    return short_name


def _newsapi_records(
    symbol: str, company: str | None, api_key: str, get: HttpGet
) -> list[dict[str, Any]]:
    """Ask NewsAPI for recent articles and shape them like yfinance records.

    Only titles are searched, because searching the full text brings back
    many articles that just mention the company in passing. The company
    name is searched on its own when we have it: a bare ticker like "T"
    matches almost any title.

    Raises:
        NewsDataError: If NewsAPI answers with an error, for example a bad
            key or the daily request limit.
    """
    query = f'"{company}"' if company else f'"{symbol}"'
    response = get(
        NEWSAPI_URL,
        params={
            "q": query,
            "searchIn": "title",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": NEWSAPI_PAGE_SIZE,
        },
        headers={"X-Api-Key": api_key},
        timeout=NEWSAPI_TIMEOUT,
    )
    data = response.json()
    if data.get("status") != "ok":
        raise NewsDataError(f"NewsAPI error: {data.get('message') or data.get('code')}")

    records: list[dict[str, Any]] = []
    for item in data.get("articles") or []:
        if not isinstance(item, Mapping):
            continue
        title = item.get("title")
        # NewsAPI keeps deleted articles in results with the title "[Removed]".
        if not isinstance(title, str) or title == "[Removed]":
            continue
        description = item.get("description") or ""
        content = TRUNCATED_MARKER.sub("", item.get("content") or "")
        # The content snippet often starts with the description, so only
        # join them when it does not.
        if content.startswith(description):
            body = content
        else:
            body = description + " " + content
        source = item.get("source")
        records.append(
            {
                "uuid": item.get("url"),
                "title": title,
                "summary": body,
                "publisher": source.get("name") if isinstance(source, Mapping) else None,
                "pubDate": item.get("publishedAt"),
            }
        )
    return records


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
    settings: Settings | None = None,
    http_get: HttpGet | None = None,
) -> list[RawArticle]:
    """Fetch recent news and normalize it for Mina's news chain.

    Args:
        run: Research run whose symbol should be fetched.
        ticker_factory: Injectable replacement for ``yfinance.Ticker``.
        search_factory: Injectable replacement for the Search fallback.
        settings: Environment snapshot; NEWSAPI_KEY turns on NewsAPI.
        http_get: Injectable replacement for ``requests.get`` (NewsAPI).

    Returns:
        Articles that have both a title and usable body text. Empty and
        malformed provider records are skipped.

    Raises:
        NewsDataError: If none of the sources returns a usable article.
    """
    make_ticker = ticker_factory or yf.Ticker
    ticker = make_ticker(run.symbol)
    # A Yahoo problem should not stop us from trying the other sources,
    # so treat it like an empty result.
    try:
        ticker_records = ticker.news or []
    except PROVIDER_ERRORS:
        ticker_records = []
    articles = _to_articles(ticker_records, run.symbol)
    if articles:
        return articles

    # Ticker.news came back empty (or failed). Try NewsAPI next if there is a key,
    # because it still gives article text. Any NewsAPI problem (bad key,
    # daily limit, network) just moves on to Search.
    current_settings = settings or load_settings()
    api_key = current_settings.values.get("NEWSAPI_KEY")
    if api_key:
        try:
            records = _newsapi_records(
                run.symbol, _company_name(ticker, run.symbol), api_key, http_get or requests.get
            )
        except (requests.RequestException, ValueError, NewsDataError):
            records = []
        articles = _to_articles(records, run.symbol)
        if articles:
            return articles

    # Last resort: yfinance Search. It can also return stories about other
    # companies, so keep only the ones tagged with this symbol (or untagged).
    search = search_factory or _search_news
    try:
        found = search(run.symbol).news or []
    except PROVIDER_ERRORS as error:
        raise NewsDataError(f"No news found for {run.symbol}; Search failed: {error}") from error
    search_records: list[Any] = []
    for record in found:
        if not isinstance(record, Mapping):
            continue
        related = record.get("relatedTickers")
        if isinstance(related, list) and related and run.symbol not in related:
            continue
        search_records.append(record)
    articles = _to_articles(search_records, run.symbol, title_as_body=True)
    if not articles:
        raise NewsDataError(f"No news found for {run.symbol} from Yahoo or NewsAPI.")
    return articles
