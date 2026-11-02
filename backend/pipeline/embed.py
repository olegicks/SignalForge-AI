"""Embed step: give every stored news item and signal a vector for RAG retrieval.

Only items without an embedding are sent to the API, so re-runs cost nothing. Signals are
re-embedded when their text changes (a same-day re-run can rewrite a signal).
"""

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.models import NewsEmbedding, NewsItem, Signal, SignalEmbedding
from pipeline.embeddings import Embedder, EmbeddingError

logger = logging.getLogger(__name__)

SUMMARY_MAX_CHARS = 1000
# Upper bound per run, so a backfill of a large history is spread over several runs.
MAX_ITEMS_PER_RUN = 5000


@dataclass
class EmbedSummary:
    news: int = 0
    signals: int = 0
    tokens: int = 0


def news_text(item: NewsItem) -> str:
    summary = (item.summary or "").strip()[:SUMMARY_MAX_CHARS]
    return f"{item.title.strip()}\n{summary}".strip()


def signal_text(signal: Signal) -> str:
    factors = "; ".join(signal.key_factors or [])
    return (
        f"{signal.ticker} signal on {signal.as_of_date.isoformat()}: {signal.signal}, "
        f"score {signal.score}/10, risk {signal.risk}, confidence {signal.confidence:.2f}. "
        f"{signal.reasoning} Key factors: {factors}"
    ).strip()


def content_hash(text_value: str) -> str:
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def check_embedding_dim(session: Session, dim: int) -> None:
    """Fail early with a clear message if EMBEDDING_DIM differs from the database column."""
    # For pgvector columns, atttypmod holds the declared dimension.
    column_dim = session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'news_embeddings'::regclass AND attname = 'embedding'"
        )
    ).scalar()
    if column_dim != dim:
        raise EmbeddingError(
            f"EMBEDDING_DIM={dim} but the database stores vectors of size {column_dim}. "
            "Changing the size needs a new migration and re-embedding everything."
        )


def _batches(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def pending_news(session: Session, limit: int = MAX_ITEMS_PER_RUN) -> list[NewsItem]:
    embedded = select(NewsEmbedding.news_item_id).where(NewsEmbedding.news_item_id == NewsItem.id)
    stmt = select(NewsItem).where(~embedded.exists()).order_by(NewsItem.id).limit(limit)
    return list(session.scalars(stmt))


def pending_signals(session: Session, limit: int = MAX_ITEMS_PER_RUN) -> list[Signal]:
    """Signals with no embedding, or whose text changed since it was embedded."""
    rows = session.execute(
        select(Signal, SignalEmbedding.content_hash)
        .outerjoin(SignalEmbedding, SignalEmbedding.signal_id == Signal.id)
        .order_by(Signal.id)
    ).all()
    stale = [s for s, stored_hash in rows if stored_hash != content_hash(signal_text(s))]
    return stale[:limit]


def embed_pending(session: Session, embedder: Embedder, batch_size: int = 100) -> EmbedSummary:
    """Embed everything still missing and commit after each batch."""
    check_embedding_dim(session, embedder.dim)
    summary = EmbedSummary()

    for batch in _batches(pending_news(session), batch_size):
        result = embedder.embed([news_text(item) for item in batch])
        stmt = insert(NewsEmbedding).values(
            [
                {"news_item_id": item.id, "embedding": vector, "model": embedder.model_name}
                for item, vector in zip(batch, result.vectors, strict=True)
            ]
        )
        session.execute(stmt.on_conflict_do_nothing(index_elements=["news_item_id"]))
        session.commit()
        summary.news += len(batch)
        summary.tokens += result.tokens

    for batch in _batches(pending_signals(session), batch_size):
        texts = [signal_text(s) for s in batch]
        result = embedder.embed(texts)
        stmt = insert(SignalEmbedding).values(
            [
                {
                    "signal_id": s.id,
                    "embedding": vector,
                    "content_hash": content_hash(t),
                    "model": embedder.model_name,
                }
                for s, t, vector in zip(batch, texts, result.vectors, strict=True)
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["signal_id"],
            set_={
                "embedding": stmt.excluded.embedding,
                "content_hash": stmt.excluded.content_hash,
                "model": stmt.excluded.model,
            },
        )
        session.execute(stmt)
        session.commit()
        summary.signals += len(batch)
        summary.tokens += result.tokens

    logger.info(
        "embed: news=%d signals=%d tokens=%d", summary.news, summary.signals, summary.tokens
    )
    return summary
