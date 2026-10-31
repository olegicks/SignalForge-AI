"""Fill in 7-day and 30-day outcomes for past signals, to build the track record."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from core.models import Signal
from pipeline.collectors.prices import download_closes

logger = logging.getLogger(__name__)

HORIZONS = (7, 30)

DownloadFn = Callable[[list[str], date, date], dict[str, pd.Series]]


@dataclass
class EvaluationSummary:
    candidates: int = 0
    filled_7d: int = 0
    filled_30d: int = 0


def first_close_on_or_after(closes: pd.Series, target: date) -> tuple[date, float] | None:
    """The first available close on or after `target`. `closes` is indexed by date."""
    later = closes[[day >= target for day in closes.index]]
    if later.empty:
        return None
    later = later.sort_index()
    return later.index[0], float(later.iloc[0])


def simple_return(price: float, base: float) -> float:
    return round(price / base - 1, 6)


def _pending_filter(today: date) -> ColumnElement[bool]:
    return or_(
        (Signal.evaluated_7d_at.is_(None)) & (Signal.as_of_date <= today - timedelta(days=7)),
        (Signal.evaluated_30d_at.is_(None)) & (Signal.as_of_date <= today - timedelta(days=30)),
    )


def evaluate_signals(
    session: Session,
    today: date,
    download: DownloadFn | None = None,
    now: datetime | None = None,
) -> EvaluationSummary:
    """Evaluate every signal that is old enough and not yet evaluated.

    Only closes from before `today` are used, so a partial intraday price never counts.
    Signals whose target close does not exist yet are left for a later run.
    """
    now = now or datetime.now(UTC)
    download = download or download_closes
    summary = EvaluationSummary()
    pending = list(session.scalars(select(Signal).where(_pending_filter(today))))
    summary.candidates = len(pending)
    if not pending:
        logger.info("evaluate: nothing to do")
        return summary

    tickers = sorted({s.ticker for s in pending})
    start = min(s.as_of_date for s in pending) + timedelta(days=min(HORIZONS))
    end = today - timedelta(days=1)
    closes = download(tickers, start, end)
    logger.info(
        "evaluate: candidates=%d tickers=%d window=%s..%s", len(pending), len(tickers), start, end
    )

    for signal in pending:
        series = closes.get(signal.ticker)
        if series is None or series.empty:
            continue
        series = series[[day < today for day in series.index]]
        base = float(signal.price_at_signal)
        for horizon in HORIZONS:
            if getattr(signal, f"evaluated_{horizon}d_at") is not None:
                continue
            target = signal.as_of_date + timedelta(days=horizon)
            if target > today:
                continue
            found = first_close_on_or_after(series, target)
            if found is None:
                continue
            _, price = found
            setattr(signal, f"price_{horizon}d", Decimal(str(round(price, 4))))
            setattr(signal, f"return_{horizon}d", simple_return(price, base))
            setattr(signal, f"evaluated_{horizon}d_at", now)
            if horizon == 7:
                summary.filled_7d += 1
            else:
                summary.filled_30d += 1

    session.flush()
    logger.info("evaluate: filled_7d=%d filled_30d=%d", summary.filled_7d, summary.filled_30d)
    return summary
