"""Small builders for test data."""

from datetime import UTC, date, datetime, timedelta

from pipeline.analyzer.base import SignalResult
from pipeline.collectors.news import NewsArticle
from pipeline.collectors.prices import PriceMetrics

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)


def make_metrics(ticker: str = "AAPL", last_close: float = 100.0) -> PriceMetrics:
    return PriceMetrics(
        ticker=ticker,
        last_close=last_close,
        last_date=date(2026, 10, 29),
        change_1d_pct=1.0,
        change_5d_pct=-2.0,
        change_30d_pct=None,
        volume_vs_20d_avg=1.5,
    )


def make_article(i: int = 1, summary: str | None = "Short summary.") -> NewsArticle:
    return NewsArticle(
        title=f"Headline number {i}",
        summary=summary,
        url=f"https://news.example.com/{i}",
        source="Reuters",
        published_at=NOW - timedelta(hours=i),
    )


def make_result(**overrides: object) -> SignalResult:
    values: dict[str, object] = {
        "signal": "bullish",
        "score": 7,
        "risk": "medium",
        "confidence": 0.6,
        "reasoning": "Demand looks solid.",
        "key_factors": ["demand"],
        "sources": ["https://news.example.com/1"],
        "model": "test-model",
        "input_tokens": 500,
        "output_tokens": 100,
    }
    values.update(overrides)
    return SignalResult(**values)
