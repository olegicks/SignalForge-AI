from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import NewsItem, PipelineRun, PriceBar, Signal
from pipeline import run as pipeline_run
from pipeline.analyzer.base import Analyzer, SignalResult
from pipeline.collectors.news import NewsArticle
from pipeline.collectors.prices import PriceMetrics
from pipeline.run import Options, final_status, run_pipeline
from tests.factories import NOW, make_article, make_result

WATCHLIST = """
tickers:
  - { ticker: AAPL, name: Apple, query: "Apple stock" }
  - { ticker: MSFT, name: Microsoft, query: "Microsoft stock" }
"""


class FakeAnalyzer(Analyzer):
    def __init__(self, score: int = 7) -> None:
        self.score = score
        self.calls: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def analyze(self, ticker: str, metrics: PriceMetrics, news: list[NewsArticle]) -> SignalResult:
        self.calls.append(ticker)
        return make_result(score=self.score, model="fake-model", sources=[news[0].url])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    path = tmp_path / "watchlist.yaml"
    path.write_text(WATCHLIST, encoding="utf-8")
    return Settings(
        _env_file=None,
        watchlist_path=path,
        openai_price_input_per_1m=1.0,
        openai_price_output_per_1m=4.0,
    )


@pytest.fixture
def fake_sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[NewsArticle]]:
    """Mock yfinance and RSS. Tests can change the news per ticker through the returned dict."""
    news_by_ticker = {"AAPL": [make_article(1), make_article(2)], "MSFT": [make_article(3)]}

    def fake_history(ticker: str) -> pd.DataFrame:
        index = pd.bdate_range("2026-08-03", "2026-10-29", tz="America/New_York")
        return pd.DataFrame({"Close": 100.0, "Volume": 1000.0}, index=index)

    def fake_news(ticker: str, query: str, **_: object) -> list[NewsArticle]:
        return news_by_ticker[ticker]

    monkeypatch.setattr(pipeline_run, "fetch_history", fake_history)
    monkeypatch.setattr(pipeline_run, "collect_news", fake_news)
    # No signals are old enough here, but never let evaluate reach yfinance.
    monkeypatch.setattr("pipeline.evaluate.download_closes", lambda *_: {})
    return news_by_ticker


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.mark.parametrize(
    ("processed", "failed", "expected"),
    [(3, 0, "success"), (2, 1, "partial"), (0, 3, "failed"), (0, 0, "failed")],
)
def test_final_status(processed: int, failed: int, expected: str) -> None:
    assert final_status(processed, failed) == expected


def test_full_run_saves_everything(
    db_session: Session, settings: Settings, fake_sources: dict
) -> None:
    analyzer = FakeAnalyzer()
    summary = run_pipeline(Options(), settings, db_session, analyzer, now=NOW)

    assert summary.status == "success"
    assert analyzer.calls == ["AAPL", "MSFT"]
    run = db_session.scalars(select(PipelineRun)).one()
    assert run.status == "success" and run.finished_at is not None
    assert (run.tickers_processed, run.tickers_failed) == (2, 0)
    assert (run.input_tokens, run.output_tokens) == (1000, 200)
    # 1000 * $1/1M + 200 * $4/1M
    assert float(run.est_cost_usd) == pytest.approx(0.0018)
    assert run.model == "fake-model"

    signals = db_session.scalars(select(Signal).order_by(Signal.ticker)).all()
    assert [s.ticker for s in signals] == ["AAPL", "MSFT"]
    assert signals[0].as_of_date == date(2026, 10, 30)
    assert float(signals[0].price_at_signal) == 100.0
    assert count(db_session, NewsItem) == 3
    assert count(db_session, PriceBar) > 0


def test_run_embeds_and_counts_embedding_cost(
    db_session: Session, settings: Settings, fake_sources: dict
) -> None:
    from tests.test_embed import FakeEmbedder

    settings.openai_embedding_price_per_1m = 2.0
    embedder = FakeEmbedder()
    summary = run_pipeline(Options(), settings, db_session, FakeAnalyzer(), NOW, embedder=embedder)

    # 3 news items + 2 signals, 3 fake tokens each.
    assert summary.embedding_tokens == 15
    run = db_session.scalars(select(PipelineRun)).one()
    assert run.embedding_tokens == 15
    # LLM part as in test_full_run_saves_everything, plus 15 * $2/1M.
    assert float(run.est_cost_usd) == pytest.approx(0.0018 + 0.00003)


def test_embed_failure_does_not_fail_the_run(
    db_session: Session, settings: Settings, fake_sources: dict
) -> None:
    from tests.test_embed import FakeEmbedder

    broken = FakeEmbedder(dim=3)  # wrong size for the database column
    summary = run_pipeline(Options(), settings, db_session, FakeAnalyzer(), NOW, embedder=broken)
    assert summary.status == "success"
    assert any(e.startswith("embed:") for e in summary.errors)


def test_rerun_same_day_is_idempotent(
    db_session: Session, settings: Settings, fake_sources: dict
) -> None:
    run_pipeline(Options(), settings, db_session, FakeAnalyzer(score=7), now=NOW)
    bars_after_first = count(db_session, PriceBar)
    run_pipeline(Options(), settings, db_session, FakeAnalyzer(score=3), now=NOW)

    signals = db_session.scalars(select(Signal)).all()
    assert len(signals) == 2
    assert {s.score for s in signals} == {3}
    latest_run = db_session.scalars(select(PipelineRun).order_by(PipelineRun.id.desc())).first()
    assert {s.run_id for s in signals} == {latest_run.id}
    assert count(db_session, NewsItem) == 3
    assert count(db_session, PriceBar) == bars_after_first


def test_one_failing_ticker_gives_partial(
    db_session: Session,
    settings: Settings,
    fake_sources: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_history = pipeline_run.fetch_history

    def flaky_history(ticker: str) -> pd.DataFrame:
        if ticker == "AAPL":
            raise ConnectionError("yfinance down")
        return real_history(ticker)

    monkeypatch.setattr(pipeline_run, "fetch_history", flaky_history)
    summary = run_pipeline(Options(), settings, db_session, FakeAnalyzer(), now=NOW)

    assert summary.status == "partial"
    run = db_session.scalars(select(PipelineRun)).one()
    assert (run.tickers_processed, run.tickers_failed) == (1, 1)
    assert "AAPL: ConnectionError: yfinance down" in run.error_summary
    assert [s.ticker for s in db_session.scalars(select(Signal))] == ["MSFT"]


def test_all_failing_gives_failed(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline_run, "fetch_history", lambda _t: (_ for _ in ()).throw(RuntimeError("x"))
    )
    summary = run_pipeline(Options(), settings, db_session, FakeAnalyzer(), now=NOW)
    assert summary.status == "failed"


def test_late_run_uses_previous_close_not_intraday_price(
    db_session: Session,
    settings: Settings,
    fake_sources: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The run is dated 2026-10-30 but started after the US open, so yfinance includes a
    # still-trading session for that day with an intraday "close" of 123.
    def history_with_live_session(ticker: str) -> pd.DataFrame:
        index = pd.bdate_range("2026-08-03", "2026-10-30", tz="America/New_York")
        closes = [100.0] * (len(index) - 1) + [123.0]
        return pd.DataFrame({"Close": closes, "Volume": 1000.0}, index=index)

    monkeypatch.setattr(pipeline_run, "fetch_history", history_with_live_session)
    run_pipeline(Options(tickers=["AAPL"]), settings, db_session, FakeAnalyzer(), now=NOW)

    signal = db_session.scalars(select(Signal)).one()
    assert float(signal.price_at_signal) == 100.0
    bar_dates = db_session.scalars(select(PriceBar.date).where(PriceBar.ticker == "AAPL")).all()
    assert date(2026, 10, 30) not in bar_dates


def test_no_news_skips_llm(db_session: Session, settings: Settings, fake_sources: dict) -> None:
    fake_sources["MSFT"] = []
    analyzer = FakeAnalyzer()
    run_pipeline(Options(), settings, db_session, analyzer, now=NOW)

    assert analyzer.calls == ["AAPL"]
    msft = db_session.scalars(select(Signal).where(Signal.ticker == "MSFT")).one()
    assert (msft.signal, msft.confidence, msft.model) == ("neutral", 0.0, "rule:no-news")


def test_no_llm_collects_only(db_session: Session, settings: Settings, fake_sources: dict) -> None:
    summary = run_pipeline(Options(no_llm=True), settings, db_session, None, now=NOW)
    assert summary.status == "success"
    assert count(db_session, Signal) == 0
    assert count(db_session, NewsItem) == 3
    assert db_session.scalars(select(PipelineRun)).one().model is None


def test_dry_run_touches_no_database(settings: Settings, fake_sources: dict) -> None:
    summary = run_pipeline(Options(dry_run=True), settings, None, FakeAnalyzer(), now=NOW)
    assert summary.status == "success"
    assert [o.result.score for o in summary.outcomes if o.result] == [7, 7]


def test_tickers_subset(db_session: Session, settings: Settings, fake_sources: dict) -> None:
    analyzer = FakeAnalyzer()
    run_pipeline(Options(tickers=["MSFT"]), settings, db_session, analyzer, now=NOW)
    assert analyzer.calls == ["MSFT"]


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-11-02T06:00:00+00:00", 72),  # Monday: reaches back to Friday morning
        ("2026-11-03T06:00:00+00:00", 48),  # Tuesday
        ("2026-11-06T06:00:00+00:00", 48),  # Friday
    ],
)
def test_news_lookback_widens_on_mondays(day: str, expected: int) -> None:
    assert pipeline_run.news_lookback_hours(48, datetime.fromisoformat(day)) == expected


def test_main_exits_nonzero_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Built without the .env file so a developer's real key can never be picked up here.
    monkeypatch.setattr(
        pipeline_run, "get_settings", lambda: Settings(_env_file=None, openai_model="x")
    )
    assert pipeline_run.main(["--dry-run"]) == 1
