from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.models import PipelineRun, Signal


def make_signal(run: PipelineRun, **overrides: object) -> Signal:
    values: dict[str, object] = {
        "run": run,
        "ticker": "AAPL",
        "as_of_date": date(2026, 10, 1),
        "signal": "bullish",
        "score": 7,
        "risk": "medium",
        "confidence": 0.6,
        "reasoning": "Test.",
        "key_factors": ["a"],
        "sources": ["https://example.com/a"],
        "price_at_signal": Decimal("100.0"),
        "model": "test-model",
    }
    values.update(overrides)
    return Signal(**values)


def test_migration_creates_all_tables(db_engine: Engine) -> None:
    tables = set(inspect(db_engine).get_table_names())
    assert {"pipeline_runs", "news_items", "signals", "price_bars"} <= tables


def test_signal_roundtrip_with_jsonb(db_session: Session) -> None:
    run = PipelineRun(model="test-model")
    db_session.add(make_signal(run, key_factors=["earnings beat", "guidance up"]))
    db_session.flush()

    stored = db_session.query(Signal).one()
    assert stored.key_factors == ["earnings beat", "guidance up"]
    assert stored.run.status == "running"
    assert stored.return_7d is None


def test_ticker_and_date_are_unique(db_session: Session) -> None:
    run = PipelineRun(model="test-model")
    db_session.add_all([make_signal(run), make_signal(run, score=3)])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_score_check_constraint(db_session: Session) -> None:
    db_session.add(make_signal(PipelineRun(model="test-model"), score=11))
    with pytest.raises(IntegrityError):
        db_session.flush()
