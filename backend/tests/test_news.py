import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from pipeline.collectors import news
from pipeline.collectors.news import NewsArticle

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)


def article(title: str, url: str, hours_ago: float, source: str = "Reuters") -> NewsArticle:
    return NewsArticle(
        title=title,
        summary=None,
        url=url,
        source=source,
        published_at=NOW - timedelta(hours=hours_ago),
    )


def test_filter_recent_respects_lookback() -> None:
    items = [
        article("fresh", "https://a.com/1", 1),
        article("edge", "https://a.com/2", 47.9),
        article("old", "https://a.com/3", 49),
        article("future", "https://a.com/4", -2),
    ]
    kept = news.filter_recent(items, NOW, lookback_hours=48)
    assert [a.title for a in kept] == ["fresh", "edge"]


def test_dedupe_by_url_keeps_newest() -> None:
    items = [
        article("Older copy", "https://a.com/story", 5),
        article("Newer copy", "https://A.com/story/", 1),
    ]
    kept = news.dedupe(items)
    assert [a.title for a in kept] == ["Newer copy"]


def test_dedupe_by_near_identical_title() -> None:
    items = [
        article("Apple beats earnings expectations", "https://a.com/1", 3),
        article("Apple beats earnings expectations!", "https://b.com/2", 2),
        article("Apple unveils new iPhone", "https://c.com/3", 1),
    ]
    kept = news.dedupe(items)
    assert [a.url for a in kept] == ["https://c.com/3", "https://b.com/2"]


def test_parse_yahoo_item_new_format() -> None:
    item = {
        "id": "x",
        "content": {
            "title": " Apple rises ",
            "summary": "Shares up.",
            "pubDate": "2026-10-30T05:00:00Z",
            "provider": {"displayName": "Bloomberg"},
            "canonicalUrl": {"url": "https://finance.yahoo.com/news/apple"},
        },
    }
    parsed = news.parse_yahoo_item(item)
    assert parsed is not None
    assert parsed.title == "Apple rises"
    assert parsed.source == "Bloomberg"
    assert parsed.published_at == datetime(2026, 10, 30, 5, 0, tzinfo=UTC)


def test_parse_yahoo_item_old_format_and_garbage() -> None:
    old = {
        "title": "Old style",
        "link": "https://x.com/old",
        "publisher": "MarketWatch",
        "providerPublishTime": int(NOW.timestamp()),
    }
    parsed = news.parse_yahoo_item(old)
    assert parsed is not None and parsed.published_at == NOW
    assert news.parse_yahoo_item({"content": {"title": "no url"}}) is None


def test_parse_google_entry_strips_source_suffix() -> None:
    entry = {
        "title": "Nvidia hits record - Reuters",
        "link": "https://news.google.com/rss/articles/abc",
        "source": {"title": "Reuters"},
        "published_parsed": time.gmtime(NOW.timestamp()),
    }
    parsed = news.parse_google_entry(entry)
    assert parsed is not None
    assert parsed.title == "Nvidia hits record"
    assert parsed.summary is None
    assert parsed.published_at == NOW


def test_collect_news_merges_filters_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    headlines = ["Chip demand rises", "CEO interview", "New store opens", "Analyst cuts", "Lawsuit"]
    yahoo = [article(title, f"https://y.com/{i}", i + 1) for i, title in enumerate(headlines)]
    google = [
        article("Chip demand rises", "https://g.com/dup", 1.5),
        article("Google exclusive", "https://g.com/1", 0.5),
        article("Too old", "https://g.com/old", 100),
    ]
    monkeypatch.setattr(news, "fetch_yahoo_news", lambda _t: yahoo)
    monkeypatch.setattr(news, "fetch_google_news", lambda _q, _h: google)

    result = news.collect_news("AAPL", "Apple", lookback_hours=48, max_items=4, now=NOW)

    assert len(result) == 4
    assert result[0].title == "Google exclusive"
    assert "Too old" not in [a.title for a in result]
    assert len({a.title for a in result}) == 4


def test_collect_news_survives_one_source_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news, "fetch_yahoo_news", MagicMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr(
        news, "fetch_google_news", lambda _q, _h: [article("Only one", "https://g.com/1", 1)]
    )
    result = news.collect_news("AAPL", "Apple", lookback_hours=48, max_items=8, now=NOW)
    assert [a.title for a in result] == ["Only one"]
