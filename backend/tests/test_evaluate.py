from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from core.models import PipelineRun, Signal
from pipeline.evaluate import evaluate_signals, first_close_on_or_after, simple_return

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
TODAY = NOW.date()


def series(points: dict[str, float]) -> pd.Series:
    return pd.Series(list(points.values()), index=[date.fromisoformat(d) for d in points])


def test_first_close_on_target_date() -> None:
    closes = series({"2026-10-08": 101.0, "2026-10-09": 102.0})
    assert first_close_on_or_after(closes, date(2026, 10, 8)) == (date(2026, 10, 8), 101.0)


def test_first_close_after_weekend_target() -> None:
    # Target is a Saturday: the next close is Monday's.
    closes = series({"2026-10-09": 100.0, "2026-10-12": 105.0, "2026-10-13": 106.0})
    assert first_close_on_or_after(closes, date(2026, 10, 10)) == (date(2026, 10, 12), 105.0)


def test_first_close_none_when_no_data_yet() -> None:
    assert first_close_on_or_after(series({"2026-10-01": 1.0}), date(2026, 10, 5)) is None


@pytest.mark.parametrize(
    ("price", "base", "expected"), [(110, 100, 0.1), (90, 100, -0.1), (100, 100, 0.0)]
)
def test_simple_return(price: float, base: float, expected: float) -> None:
    assert simple_return(price, base) == pytest.approx(expected)


def add_signal(session: Session, run: PipelineRun, ticker: str, as_of: date) -> Signal:
    signal = Signal(
        run=run,
        ticker=ticker,
        as_of_date=as_of,
        signal="bullish",
        score=7,
        risk="low",
        confidence=0.7,
        reasoning="r",
        key_factors=[],
        sources=[],
        price_at_signal=Decimal("100"),
        model="m",
    )
    session.add(signal)
    return signal


def test_evaluate_signals_fills_outcomes(db_session: Session) -> None:
    run = PipelineRun(model="m")
    old = add_signal(db_session, run, "AAPL", date(2026, 9, 29))  # 31 days old
    week = add_signal(db_session, run, "MSFT", date(2026, 10, 22))  # 8 days old
    fresh = add_signal(db_session, run, "NVDA", date(2026, 10, 28))  # too new
    db_session.flush()

    calls: list[tuple[list[str], date, date]] = []

    def fake_download(tickers: list[str], start: date, end: date) -> dict[str, pd.Series]:
        calls.append((tickers, start, end))
        return {
            "AAPL": series({"2026-10-06": 104.0, "2026-10-29": 120.0, "2026-10-30": 999.0}),
            "MSFT": series({"2026-10-29": 95.0}),
        }

    summary = evaluate_signals(db_session, today=TODAY, download=fake_download, now=NOW)

    assert calls == [(["AAPL", "MSFT"], date(2026, 10, 6), date(2026, 10, 29))]
    assert (summary.candidates, summary.filled_7d, summary.filled_30d) == (2, 2, 1)
    assert old.price_7d == Decimal("104") and old.return_7d == pytest.approx(0.04)
    # Today's (possibly intraday) close of 999 is ignored.
    assert old.price_30d == Decimal("120") and old.return_30d == pytest.approx(0.2)
    assert week.return_7d == pytest.approx(-0.05) and week.return_30d is None
    assert fresh.evaluated_7d_at is None

    # A second pass has nothing new to fill for the 7d horizon.
    again = evaluate_signals(db_session, today=TODAY, download=fake_download, now=NOW)
    assert again.filled_7d == 0


def test_evaluate_leaves_signal_pending_without_target_close(db_session: Session) -> None:
    signal = add_signal(db_session, PipelineRun(model="m"), "AAPL", date(2026, 10, 22))
    db_session.flush()

    summary = evaluate_signals(
        db_session,
        today=TODAY,
        download=lambda *_: {"AAPL": series({"2026-10-27": 1.0})},
        now=NOW,
    )
    assert summary.filled_7d == 0
    assert signal.evaluated_7d_at is None
