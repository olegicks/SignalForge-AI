from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.routes import database_ok
from app.main import app
from core.db import get_session
from core.models import NewsItem, PipelineRun, PriceBar, Signal


def make_signal(run: PipelineRun, ticker: str, as_of: date, **overrides: object) -> Signal:
    values: dict[str, object] = {
        "run": run,
        "ticker": ticker,
        "as_of_date": as_of,
        "signal": "bullish",
        "score": 6,
        "risk": "medium",
        "confidence": 0.5,
        "reasoning": f"{ticker} reasoning.",
        "key_factors": ["factor"],
        "sources": ["https://news.example.com/1"],
        "price_at_signal": Decimal("100"),
        "model": "test-model",
    }
    values.update(overrides)
    return Signal(**values)


@pytest.fixture
def seeded(db_session: Session) -> Session:
    old_run = PipelineRun(
        status="success",
        started_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
        tickers_processed=2,
        model="test-model",
    )
    new_run = PipelineRun(
        status="partial",
        started_at=datetime(2026, 10, 30, 6, tzinfo=UTC),
        tickers_processed=2,
        tickers_failed=1,
        est_cost_usd=Decimal("0.0012"),
        model="test-model",
    )
    db_session.add_all(
        [
            make_signal(
                old_run,
                "AAPL",
                date(2026, 9, 1),
                return_7d=0.03,
                return_30d=-0.02,
                price_7d=Decimal("103"),
                price_30d=Decimal("98"),
                confidence=0.8,
            ),
            make_signal(
                old_run,
                "MSFT",
                date(2026, 9, 1),
                signal="bearish",
                score=3,
                return_7d=-0.01,
                confidence=0.3,
            ),
            make_signal(new_run, "AAPL", date(2026, 10, 30), score=8),
            make_signal(new_run, "MSFT", date(2026, 10, 30), score=4, confidence=0.9),
            NewsItem(
                ticker="AAPL",
                title="Apple news",
                url="https://news.example.com/1",
                source="Reuters",
                published_at=datetime(2026, 10, 29, 12, tzinfo=UTC),
            ),
            PriceBar(ticker="AAPL", date=date(2026, 10, 28), close=Decimal("99.5")),
            PriceBar(ticker="AAPL", date=date(2026, 10, 29), close=Decimal("100")),
        ]
    )
    db_session.flush()
    return db_session


@pytest.fixture
def client(seeded: Session) -> Iterator[TestClient]:
    def override_session() -> Iterator[Session]:
        yield seeded

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[database_ok] = lambda: True
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "database": True}
    app.dependency_overrides[database_ok] = lambda: False
    assert client.get("/health").json() == {"status": "degraded", "database": False}


def test_runs(client: TestClient) -> None:
    runs = client.get("/runs", params={"limit": 5}).json()
    assert [r["status"] for r in runs] == ["partial", "success"]
    assert runs[0]["est_cost_usd"] == pytest.approx(0.0012)
    assert client.get("/runs", params={"limit": 0}).status_code == 422


def test_latest_signals_sorted_by_score(client: TestClient) -> None:
    body = client.get("/signals/latest").json()
    assert body["as_of_date"] == "2026-10-30"
    assert [s["ticker"] for s in body["signals"]] == ["AAPL", "MSFT"]

    by_conf = client.get("/signals/latest", params={"sort": "confidence"}).json()
    assert [s["ticker"] for s in by_conf["signals"]] == ["MSFT", "AAPL"]


def test_signal_history_filters(client: TestClient) -> None:
    all_aapl = client.get("/signals", params={"ticker": "aapl"}).json()
    assert [s["as_of_date"] for s in all_aapl] == ["2026-10-30", "2026-09-01"]

    window = client.get("/signals", params={"from": "2026-10-01", "to": "2026-10-31"}).json()
    assert {s["as_of_date"] for s in window} == {"2026-10-30"}


def test_ticker_detail(client: TestClient) -> None:
    body = client.get("/tickers/AAPL").json()
    assert body["ticker"] == "AAPL"
    assert body["name"] == "Apple"
    assert len(body["signals"]) == 2
    assert body["news"][0]["title"] == "Apple news"
    assert [p["close"] for p in body["prices"]] == [99.5, 100.0]

    assert client.get("/tickers/NOPE").status_code == 404


def test_track_record(client: TestClient) -> None:
    body = client.get("/stats/track-record").json()
    assert body["total_signals"] == 4

    seven, thirty = body["horizons"]
    assert seven["horizon_days"] == 7
    assert (seven["directional"], seven["hits"], seven["hit_rate"]) == (2, 2, 1.0)
    assert thirty["horizon_days"] == 30
    assert (thirty["directional"], thirty["hits"], thirty["hit_rate"]) == (1, 0, 0.0)
    assert [s["ticker"] for s in body["recent_evaluated"]] == ["AAPL", "MSFT"]


def test_server_error_keeps_cors_headers() -> None:
    """A crash (e.g. missing tables) must reach the browser as a 500, not a CORS failure."""

    def broken_session() -> Iterator[Session]:
        raise RuntimeError("relation pipeline_runs does not exist")
        yield  # pragma: no cover

    app.dependency_overrides[get_session] = broken_session
    try:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/runs", headers={"Origin": "http://localhost:5173"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_api_is_read_only(client: TestClient) -> None:
    assert client.post("/signals").status_code == 405
    assert client.get("/openapi.json").status_code == 200
