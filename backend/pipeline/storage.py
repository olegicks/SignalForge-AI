"""Database writes for the pipeline. Upserts make re-runs on the same day safe."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.models import NewsItem, PriceBar, Signal
from pipeline.analyzer.base import SignalResult
from pipeline.collectors.news import NewsArticle


def store_news(session: Session, ticker: str, articles: list[NewsArticle]) -> int:
    """Insert articles we have not seen before (by URL). Returns how many were new."""
    if not articles:
        return 0
    rows = [
        {
            "ticker": ticker,
            "title": a.title,
            "summary": a.summary,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at,
        }
        for a in articles
    ]
    stmt = (
        insert(NewsItem)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["url"])
        .returning(NewsItem.id)
    )
    return len(session.execute(stmt).all())


def upsert_price_bars(session: Session, ticker: str, bars: list[tuple[date, float]]) -> None:
    if not bars:
        return
    stmt = insert(PriceBar).values(
        [{"ticker": ticker, "date": day, "close": Decimal(str(close))} for day, close in bars]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_price_bars_ticker_date", set_={"close": stmt.excluded.close}
    )
    session.execute(stmt)


def upsert_signal(
    session: Session,
    *,
    run_id: int,
    ticker: str,
    as_of_date: date,
    result: SignalResult,
    price_at_signal: float,
) -> int:
    """Create or replace the signal for (ticker, as_of_date). Returns the signal id."""
    values = {
        "run_id": run_id,
        "ticker": ticker,
        "as_of_date": as_of_date,
        "signal": result.signal,
        "score": result.score,
        "risk": result.risk,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "key_factors": result.key_factors,
        "sources": result.sources,
        "price_at_signal": Decimal(str(price_at_signal)),
        "model": result.model,
    }
    stmt = insert(Signal).values(values)
    update_columns = {k: stmt.excluded[k] for k in values if k not in ("ticker", "as_of_date")}
    stmt = stmt.on_conflict_do_update(
        constraint="uq_signals_ticker_date", set_=update_columns
    ).returning(Signal.id)
    return session.execute(stmt).scalar_one()


def count_signals(session: Session, ticker: str, as_of_date: date) -> int:
    stmt = select(Signal.id).where(Signal.ticker == ticker, Signal.as_of_date == as_of_date)
    return len(session.execute(stmt).all())
