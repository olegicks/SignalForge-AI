from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.orm import Session

from core.config import Settings
from core.models import NewsEmbedding, NewsItem, PipelineRun, Signal, SignalEmbedding
from pipeline.embed import (
    check_embedding_dim,
    embed_pending,
    news_text,
    pending_news,
)
from pipeline.embeddings import EmbeddingBatch, EmbeddingError, OpenAIEmbedder
from tests.factories import NOW

DIM = Settings(_env_file=None).embedding_dim


class FakeEmbedder:
    """Records every call; returns a simple vector per text, 3 tokens per text."""

    model_name = "fake-embedding"

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        self.calls.append(texts)
        vectors = [[1.0] + [0.0] * (self.dim - 1) for _ in texts]
        return EmbeddingBatch(vectors=vectors, tokens=3 * len(texts))


def add_news(session: Session, i: int, summary: str | None = "Summary.") -> NewsItem:
    item = NewsItem(
        ticker="AAPL",
        title=f"Headline {i}",
        summary=summary,
        url=f"https://news.example.com/{i}",
        source="Reuters",
        published_at=NOW,
    )
    session.add(item)
    return item


def add_signal(session: Session, reasoning: str = "Solid demand.") -> Signal:
    signal = Signal(
        run=PipelineRun(model="m"),
        ticker="AAPL",
        as_of_date=date(2026, 10, 30),
        signal="bullish",
        score=7,
        risk="medium",
        confidence=0.6,
        reasoning=reasoning,
        key_factors=["demand"],
        sources=[],
        price_at_signal=Decimal("100"),
        model="m",
    )
    session.add(signal)
    return signal


def test_migration_creates_vector_tables_and_hnsw_indexes(db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    assert {"news_embeddings", "signal_embeddings"} <= set(inspector.get_table_names())
    with db_engine.connect() as conn:
        indexes = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname LIKE '%hnsw'")
        ).all()
    assert len(indexes) == 2
    assert all("hnsw" in d and "vector_cosine_ops" in d for _, d in indexes)


def test_embed_step_only_processes_new_items(db_session: Session) -> None:
    add_news(db_session, 1)
    add_news(db_session, 2, summary=None)
    db_session.flush()
    embedder = FakeEmbedder()

    first = embed_pending(db_session, embedder)
    assert (first.news, first.tokens) == (2, 6)
    assert embedder.calls[0] == ["Headline 1\nSummary.", "Headline 2"]

    add_news(db_session, 3)
    db_session.flush()
    second = embed_pending(db_session, embedder)
    assert second.news == 1
    assert embedder.calls[-1] == ["Headline 3\nSummary."]

    third = embed_pending(db_session, embedder)
    assert (third.news, third.signals, third.tokens) == (0, 0, 0)
    assert db_session.scalar(select(func.count()).select_from(NewsEmbedding)) == 3


def test_embed_step_batches(db_session: Session) -> None:
    for i in range(5):
        add_news(db_session, i)
    db_session.flush()
    embedder = FakeEmbedder()
    embed_pending(db_session, embedder, batch_size=2)
    assert [len(c) for c in embedder.calls] == [2, 2, 1]


def test_signal_is_reembedded_only_when_its_text_changes(db_session: Session) -> None:
    signal = add_signal(db_session)
    db_session.flush()
    embedder = FakeEmbedder()

    assert embed_pending(db_session, embedder).signals == 1
    assert embed_pending(db_session, embedder).signals == 0

    # A same-day re-run rewrote the reasoning: the embedding must be refreshed in place.
    signal.reasoning = "Demand is weakening."
    db_session.flush()
    assert embed_pending(db_session, embedder).signals == 1
    assert db_session.scalar(select(func.count()).select_from(SignalEmbedding)) == 1
    assert "Demand is weakening." in embedder.calls[-1][0]


def test_dimension_mismatch_fails_clearly(db_session: Session) -> None:
    check_embedding_dim(db_session, DIM)  # matches the migrated column
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIM"):
        check_embedding_dim(db_session, DIM + 1)


def test_news_text_truncates_long_summaries(db_session: Session) -> None:
    item = add_news(db_session, 1, summary="x" * 5000)
    assert len(news_text(item)) < 1100
    assert pending_news(db_session)  # flushed by autoflush, not embedded yet


def test_openai_embedder_requests_dimensions_and_orders_results() -> None:
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(index=1, embedding=[0.0, 1.0]),
            SimpleNamespace(index=0, embedding=[1.0, 0.0]),
        ],
        usage=SimpleNamespace(total_tokens=12),
    )
    settings = Settings(_env_file=None, openai_embedding_model="emb-model", embedding_dim=2)
    result = OpenAIEmbedder(settings, client=client).embed(["first", "second"])

    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.tokens == 12
    kwargs = client.embeddings.create.call_args.kwargs
    assert (kwargs["model"], kwargs["dimensions"]) == ("emb-model", 2)


def test_openai_embedder_requires_a_model() -> None:
    with pytest.raises(EmbeddingError, match="OPENAI_EMBEDDING_MODEL"):
        OpenAIEmbedder(Settings(_env_file=None), client=MagicMock())
