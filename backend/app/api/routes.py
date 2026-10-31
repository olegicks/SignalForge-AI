"""Read-only API routes. There are deliberately no write endpoints."""

from datetime import date
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.schemas import (
    HealthOut,
    LatestSignalsOut,
    NewsOut,
    PricePoint,
    RunOut,
    SignalOut,
    TickerDetailOut,
    TrackRecordOut,
)
from app.stats import Outcome, horizon_stats
from core.config import get_settings
from core.db import get_engine, get_session
from core.models import NewsItem, PipelineRun, PriceBar, Signal
from pipeline.watchlist import load_watchlist

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]

LATEST_SORTS = {
    "score": (Signal.score.desc(), Signal.confidence.desc()),
    "confidence": (Signal.confidence.desc(), Signal.score.desc()),
    "ticker": (Signal.ticker.asc(),),
}


@lru_cache
def ticker_names() -> dict[str, str]:
    settings = get_settings()
    entries = load_watchlist(settings.watchlist_path, limit=1000)
    return {entry.ticker: entry.name for entry in entries}


def database_ok() -> bool:
    """Not a session dependency, so /health still answers when the DB is misconfigured."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/health", response_model=HealthOut, tags=["meta"])
def health(db_ok: Annotated[bool, Depends(database_ok)]) -> HealthOut:
    return HealthOut(status="ok" if db_ok else "degraded", database=db_ok)


@router.get("/runs", response_model=list[RunOut], tags=["runs"])
def list_runs(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list:
    stmt = select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
    return list(session.scalars(stmt))


@router.get("/signals/latest", response_model=LatestSignalsOut, tags=["signals"])
def latest_signals(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    sort: Literal["score", "confidence", "ticker"] = "score",
) -> LatestSignalsOut:
    latest_date = session.scalar(select(func.max(Signal.as_of_date)))
    if latest_date is None:
        return LatestSignalsOut(as_of_date=None, signals=[])
    stmt = (
        select(Signal)
        .where(Signal.as_of_date == latest_date)
        .order_by(*LATEST_SORTS[sort])
        .limit(limit)
    )
    signals = [SignalOut.model_validate(s) for s in session.scalars(stmt)]
    return LatestSignalsOut(as_of_date=latest_date, signals=signals)


@router.get("/signals", response_model=list[SignalOut], tags=["signals"])
def signal_history(
    session: SessionDep,
    ticker: str | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list:
    stmt = select(Signal)
    if ticker:
        stmt = stmt.where(Signal.ticker == ticker.upper())
    if date_from:
        stmt = stmt.where(Signal.as_of_date >= date_from)
    if date_to:
        stmt = stmt.where(Signal.as_of_date <= date_to)
    stmt = stmt.order_by(Signal.as_of_date.desc(), Signal.ticker).limit(limit)
    return list(session.scalars(stmt))


@router.get("/tickers/{ticker}", response_model=TickerDetailOut, tags=["tickers"])
def ticker_detail(
    ticker: str,
    session: SessionDep,
    news_limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TickerDetailOut:
    symbol = ticker.upper()
    signals = session.scalars(
        select(Signal).where(Signal.ticker == symbol).order_by(Signal.as_of_date.desc())
    ).all()
    news = session.scalars(
        select(NewsItem)
        .where(NewsItem.ticker == symbol)
        .order_by(NewsItem.published_at.desc())
        .limit(news_limit)
    ).all()
    prices = session.scalars(
        select(PriceBar).where(PriceBar.ticker == symbol).order_by(PriceBar.date)
    ).all()
    if not signals and not news and not prices:
        raise HTTPException(status_code=404, detail=f"No data for ticker {symbol}")
    return TickerDetailOut(
        ticker=symbol,
        name=ticker_names().get(symbol),
        signals=[SignalOut.model_validate(s) for s in signals],
        news=[NewsOut.model_validate(n) for n in news],
        prices=[PricePoint.model_validate(p) for p in prices],
    )


@router.get("/stats/track-record", response_model=TrackRecordOut, tags=["stats"])
def track_record(
    session: SessionDep,
    recent_limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TrackRecordOut:
    total = session.scalar(select(func.count()).select_from(Signal)) or 0

    horizons = []
    for days, column in ((7, Signal.return_7d), (30, Signal.return_30d)):
        rows = session.execute(
            select(Signal.signal, Signal.confidence, column).where(column.is_not(None))
        ).all()
        outcomes = [Outcome(signal=s, confidence=c, ret=r) for s, c, r in rows]
        horizons.append(horizon_stats(days, outcomes))

    recent = session.scalars(
        select(Signal)
        .where(Signal.return_7d.is_not(None))
        .order_by(Signal.as_of_date.desc(), Signal.ticker)
        .limit(recent_limit)
    ).all()
    return TrackRecordOut(
        total_signals=total,
        horizons=horizons,
        recent_evaluated=[SignalOut.model_validate(s) for s in recent],
    )
