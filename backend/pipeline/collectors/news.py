"""Recent news from yfinance (`Ticker.news`) and Google News RSS."""

import calendar
import logging
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote_plus

import feedparser
import yfinance as yf
from pydantic import BaseModel

from pipeline.retry import network_retry

logger = logging.getLogger(__name__)

TITLE_SIMILARITY_THRESHOLD = 0.9
YAHOO_NEWS_COUNT = 20
GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search?q={query}+when:{days}d&hl=en-US&gl=US&ceid=US:en"
)
HTTP_TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (compatible; SignalForge/0.1; research prototype)"


class NewsArticle(BaseModel):
    title: str
    summary: str | None
    url: str
    source: str
    published_at: datetime


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_yahoo_item(item: dict[str, Any]) -> NewsArticle | None:
    """Handle both the newer nested `content` format and the older flat one."""
    try:
        content = item.get("content")
        if isinstance(content, dict):
            url_info = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
            return NewsArticle(
                title=content["title"].strip(),
                summary=(content.get("summary") or None),
                url=url_info["url"],
                source=(content.get("provider") or {}).get("displayName") or "Yahoo Finance",
                published_at=_parse_iso(content["pubDate"]),
            )
        return NewsArticle(
            title=item["title"].strip(),
            summary=item.get("summary") or None,
            url=item["link"],
            source=item.get("publisher") or "Yahoo Finance",
            published_at=datetime.fromtimestamp(int(item["providerPublishTime"]), tz=UTC),
        )
    except (KeyError, TypeError, ValueError):
        logger.debug("Skipping unparseable Yahoo news item: %s", item.get("id"))
        return None


@network_retry
def fetch_yahoo_news(ticker: str) -> list[NewsArticle]:
    raw = yf.Ticker(ticker).get_news(count=YAHOO_NEWS_COUNT) or []
    return [article for item in raw if (article := parse_yahoo_item(item))]


def parse_google_entry(entry: Any) -> NewsArticle | None:
    try:
        source = (entry.get("source") or {}).get("title") or "Google News"
        title = entry["title"].strip()
        # Google appends " - Source" to every headline.
        suffix = f" - {source}"
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
        published = entry.get("published_parsed")
        if published is None:
            return None
        return NewsArticle(
            title=title,
            # Google's RSS summary just repeats the headline as HTML, so it is not worth tokens.
            summary=None,
            url=entry["link"],
            source=source,
            published_at=datetime.fromtimestamp(calendar.timegm(published), tz=UTC),
        )
    except (KeyError, TypeError, ValueError):
        return None


@network_retry
def fetch_google_news(query: str, lookback_hours: int) -> list[NewsArticle]:
    days = max(1, -(-lookback_hours // 24))
    url = GOOGLE_NEWS_URL.format(query=quote_plus(query), days=days)
    # Fetch ourselves so there is a timeout; feedparser's own fetcher has none.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        feed = feedparser.parse(response.read())
    if feed.get("bozo") and not feed.get("entries"):
        raise RuntimeError(f"Google News RSS failed: {feed.get('bozo_exception')}")
    return [article for entry in feed.entries if (article := parse_google_entry(entry))]


def filter_recent(
    articles: list[NewsArticle], now: datetime, lookback_hours: int
) -> list[NewsArticle]:
    cutoff = now - timedelta(hours=lookback_hours)
    return [a for a in articles if cutoff <= a.published_at <= now + timedelta(minutes=5)]


def _normalize_url(url: str) -> str:
    return url.strip().split("#")[0].rstrip("/").lower()


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def dedupe(articles: list[NewsArticle]) -> list[NewsArticle]:
    """Drop repeated URLs and near-identical headlines, keeping the newest copy."""
    kept: list[NewsArticle] = []
    seen_urls: set[str] = set()
    kept_titles: list[str] = []
    for article in sorted(articles, key=lambda a: a.published_at, reverse=True):
        url = _normalize_url(article.url)
        title = _normalize_title(article.title)
        if url in seen_urls:
            continue
        if any(
            SequenceMatcher(None, title, other).ratio() >= TITLE_SIMILARITY_THRESHOLD
            for other in kept_titles
        ):
            continue
        seen_urls.add(url)
        kept_titles.append(title)
        kept.append(article)
    return kept


def collect_news(
    ticker: str,
    query: str,
    *,
    lookback_hours: int,
    max_items: int,
    now: datetime | None = None,
) -> list[NewsArticle]:
    """Merge both sources. One source failing is logged and does not stop the other."""
    now = now or datetime.now(UTC)
    articles: list[NewsArticle] = []
    for name, fetch in (
        ("yahoo", lambda: fetch_yahoo_news(ticker)),
        ("google", lambda: fetch_google_news(query, lookback_hours)),
    ):
        try:
            articles.extend(fetch())
        except Exception as exc:
            logger.warning("News source %s failed for %s: %s", name, ticker, exc)

    recent = dedupe(filter_recent(articles, now, lookback_hours))
    return recent[:max_items]
