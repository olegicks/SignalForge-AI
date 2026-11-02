"""SQLAlchemy ORM models. Every schema change goes through an Alembic migration."""

from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

RUN_STATUSES = ("running", "success", "partial", "failed")
SIGNAL_TYPES = ("bullish", "bearish", "neutral")
RISK_LEVELS = ("low", "medium", "high")


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (CheckConstraint(_in_check("status", RUN_STATUSES), name="ck_run_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    tickers_processed: Mapped[int] = mapped_column(Integer, default=0)
    tickers_failed: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    model: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(Text)

    signals: Mapped[list["Signal"]] = relationship(back_populates="run")


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("ticker", "as_of_date", name="uq_signals_ticker_date"),
        CheckConstraint(_in_check("signal", SIGNAL_TYPES), name="ck_signal_type"),
        CheckConstraint(_in_check("risk", RISK_LEVELS), name="ck_signal_risk"),
        CheckConstraint("score BETWEEN 1 AND 10", name="ck_signal_score"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_signal_confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    signal: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer)
    risk: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text)
    key_factors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list)
    price_at_signal: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Outcomes, filled in later by pipeline.evaluate
    price_7d: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    return_7d: Mapped[float | None] = mapped_column(Float)
    price_30d: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    return_30d: Mapped[float | None] = mapped_column(Float)
    # Same-window return of the market benchmark (SPY), to tell skill from a rising market.
    benchmark_return_7d: Mapped[float | None] = mapped_column(Float)
    benchmark_return_30d: Mapped[float | None] = mapped_column(Float)
    evaluated_7d_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluated_30d_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[PipelineRun] = relationship(back_populates="signals")


class PriceBar(Base):
    """Daily closes, kept so the dashboard can draw a price line without calling yfinance."""

    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_price_bars_ticker_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[date] = mapped_column(Date)
    close: Mapped[Decimal] = mapped_column(Numeric(14, 4))


# Embeddings for RAG ("Ask the news"). The vector size is set by migration 0003 from
# EMBEDDING_DIM, so the ORM column is declared without a fixed dimension.


class NewsEmbedding(Base):
    __tablename__ = "news_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_item_id: Mapped[int] = mapped_column(
        ForeignKey("news_items.id", ondelete="CASCADE"), unique=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector())
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalEmbedding(Base):
    __tablename__ = "signal_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), unique=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector())
    content_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
