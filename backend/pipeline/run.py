"""Daily pipeline entrypoint.

python -m pipeline.run [--tickers AAPL,MSFT] [--dry-run] [--no-llm] [--evaluate-only]
"""

import argparse
import json
import logging
import sys
import warnings
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.config import Settings, get_settings
from core.db import get_sessionmaker
from core.models import PipelineRun
from pipeline.analyzer import Analyzer, AnalyzerError, SignalResult, get_analyzer
from pipeline.collectors.news import collect_news
from pipeline.collectors.prices import (
    completed_sessions,
    compute_metrics,
    fetch_history,
    recent_closes,
)
from pipeline.evaluate import evaluate_signals
from pipeline.storage import store_news, upsert_price_bars, upsert_signal
from pipeline.watchlist import WatchlistEntry, load_watchlist

logger = logging.getLogger("pipeline")

NO_NEWS_MODEL = "rule:no-news"
MAX_ERROR_SUMMARY_CHARS = 4000


@dataclass
class Options:
    tickers: list[str] | None = None
    dry_run: bool = False
    no_llm: bool = False
    evaluate_only: bool = False


@dataclass
class TickerOutcome:
    ticker: str
    last_close: float
    news_count: int
    new_news: int
    result: SignalResult | None = None


@dataclass
class RunSummary:
    status: str = "running"
    processed: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)
    outcomes: list[TickerOutcome] = field(default_factory=list)


def final_status(processed: int, failed: int) -> str:
    if processed == 0:
        return "failed"
    return "partial" if failed else "success"


def news_lookback_hours(base_hours: int, now: datetime) -> int:
    """The news window for this run, widened on Mondays.

    The early-morning weekday run normally looks back over the last trading day. On Monday the
    base 48 h only reaches Saturday morning, so one extra day brings Friday's news back in.
    """
    return base_hours + 24 if now.weekday() == 0 else base_hours


def no_news_result() -> SignalResult:
    """Skip the LLM entirely when there is nothing to read: cheaper and more honest."""
    return SignalResult(
        signal="neutral",
        score=5,
        risk="medium",
        confidence=0.0,
        reasoning="No recent news was found in the lookback window, so no view is taken.",
        key_factors=[],
        sources=[],
        model=NO_NEWS_MODEL,
    )


def process_ticker(
    entry: WatchlistEntry,
    *,
    settings: Settings,
    session: Session | None,
    analyzer: Analyzer | None,
    run_id: int | None,
    as_of_date: date,
    now: datetime,
) -> TickerOutcome:
    history = completed_sessions(fetch_history(entry.ticker), as_of_date)
    metrics = compute_metrics(entry.ticker, history)
    articles = collect_news(
        entry.ticker,
        entry.query,
        lookback_hours=news_lookback_hours(settings.news_lookback_hours, now),
        max_items=settings.max_news_per_ticker,
        now=now,
    )

    new_news = 0
    if session is not None:
        new_news = store_news(session, entry.ticker, articles)
        upsert_price_bars(session, entry.ticker, recent_closes(history))

    outcome = TickerOutcome(
        ticker=entry.ticker,
        last_close=metrics.last_close,
        news_count=len(articles),
        new_news=new_news,
    )
    if analyzer is None:
        return outcome

    outcome.result = (
        analyzer.analyze(entry.ticker, metrics, articles) if articles else no_news_result()
    )
    if session is not None and run_id is not None:
        upsert_signal(
            session,
            run_id=run_id,
            ticker=entry.ticker,
            as_of_date=as_of_date,
            result=outcome.result,
            price_at_signal=metrics.last_close,
        )
    return outcome


def run_pipeline(
    options: Options,
    settings: Settings,
    session: Session | None,
    analyzer: Analyzer | None,
    now: datetime | None = None,
) -> RunSummary:
    """Run steps 1-5. `session` is None for a dry run, `analyzer` is None for --no-llm."""
    now = now or datetime.now(UTC)
    as_of_date = now.date()
    summary = RunSummary()

    run: PipelineRun | None = None
    if session is not None:
        run = PipelineRun(status="running", model=analyzer.model_name if analyzer else None)
        session.add(run)
        session.commit()
        logger.info("run started id=%s", run.id)

    entries = load_watchlist(settings.watchlist_path, settings.max_tickers_per_run, options.tickers)
    logger.info("watchlist loaded tickers=%d", len(entries))

    for entry in entries:
        try:
            outcome = process_ticker(
                entry,
                settings=settings,
                session=session,
                analyzer=analyzer,
                run_id=run.id if run else None,
                as_of_date=as_of_date,
                now=now,
            )
            if session is not None:
                session.commit()
        except Exception as exc:
            if session is not None:
                session.rollback()
            summary.failed += 1
            summary.errors.append(f"{entry.ticker}: {type(exc).__name__}: {exc}")
            # Full traceback only with LOG_LEVEL=DEBUG; the one-line error is enough day to day.
            logger.error(
                "ticker failed ticker=%s error=%s: %s",
                entry.ticker,
                type(exc).__name__,
                exc,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            continue

        summary.processed += 1
        summary.outcomes.append(outcome)
        if outcome.result:
            summary.input_tokens += outcome.result.input_tokens
            summary.output_tokens += outcome.result.output_tokens
        logger.info(
            "ticker done ticker=%s close=%.2f news=%d new_news=%d signal=%s score=%s",
            entry.ticker,
            outcome.last_close,
            outcome.news_count,
            outcome.new_news,
            outcome.result.signal if outcome.result else "-",
            outcome.result.score if outcome.result else "-",
        )

    if session is not None:
        try:
            evaluate_signals(session, today=as_of_date, now=now)
            session.commit()
        except Exception as exc:
            session.rollback()
            summary.errors.append(f"evaluate: {type(exc).__name__}: {exc}")
            logger.exception("evaluate step failed")

    summary.status = final_status(summary.processed, summary.failed)
    summary.est_cost_usd = settings.estimate_cost_usd(summary.input_tokens, summary.output_tokens)

    if session is not None and run is not None:
        run.finished_at = datetime.now(UTC)
        run.status = summary.status
        run.tickers_processed = summary.processed
        run.tickers_failed = summary.failed
        run.input_tokens = summary.input_tokens
        run.output_tokens = summary.output_tokens
        run.est_cost_usd = Decimal(str(round(summary.est_cost_usd, 6)))
        run.error_summary = "\n".join(summary.errors)[:MAX_ERROR_SUMMARY_CHARS] or None
        session.commit()

    logger.info(
        "run finished status=%s processed=%d failed=%d input_tokens=%d output_tokens=%d "
        "est_cost_usd=%.6f",
        summary.status,
        summary.processed,
        summary.failed,
        summary.input_tokens,
        summary.output_tokens,
        summary.est_cost_usd,
    )
    return summary


def print_dry_run(summary: RunSummary) -> None:
    report = {
        "status": summary.status,
        "processed": summary.processed,
        "failed": summary.failed,
        "input_tokens": summary.input_tokens,
        "output_tokens": summary.output_tokens,
        "est_cost_usd": round(summary.est_cost_usd, 6),
        "errors": summary.errors,
        "tickers": [
            {
                "ticker": o.ticker,
                "last_close": o.last_close,
                "news_count": o.news_count,
                "signal": o.result.model_dump(exclude={"input_tokens", "output_tokens"})
                if o.result
                else None,
            }
            for o in summary.outcomes
        ],
    }
    print(json.dumps(report, indent=2, default=str))


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )
    # Quiet chatty libraries; httpx would log every request URL at INFO.
    for name in ("yfinance", "httpx", "httpx2", "httpcore", "openai", "urllib3", "peewee"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    warnings.filterwarnings("ignore", module="yfinance")


def parse_args(argv: list[str] | None) -> Options:
    parser = argparse.ArgumentParser(prog="python -m pipeline.run", description=__doc__)
    parser.add_argument("--tickers", help="Comma-separated subset, e.g. AAPL,MSFT")
    parser.add_argument("--dry-run", action="store_true", help="Write nothing to the database")
    parser.add_argument("--no-llm", action="store_true", help="Collect data only")
    parser.add_argument("--evaluate-only", action="store_true", help="Only fill in outcomes")
    args = parser.parse_args(argv)
    return Options(
        tickers=args.tickers.split(",") if args.tickers else None,
        dry_run=args.dry_run,
        no_llm=args.no_llm,
        evaluate_only=args.evaluate_only,
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    if options.evaluate_only:
        with get_sessionmaker()() as session:
            summary = evaluate_signals(session, today=datetime.now(UTC).date())
            if options.dry_run:
                session.rollback()
                print(json.dumps(summary.__dict__, indent=2))
            else:
                session.commit()
        return 0

    try:
        analyzer = None if options.no_llm else get_analyzer(settings)
    except AnalyzerError as exc:
        logger.error("cannot start analyzer: %s", exc)
        return 1

    if options.dry_run:
        summary = run_pipeline(options, settings, session=None, analyzer=analyzer)
        print_dry_run(summary)
    else:
        with get_sessionmaker()() as session:
            summary = run_pipeline(options, settings, session=session, analyzer=analyzer)

    return 1 if summary.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
