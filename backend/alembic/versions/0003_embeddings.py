"""pgvector embeddings for news and signals

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op
from core.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The vector size is fixed here, from EMBEDDING_DIM at migration time.
    dim = get_settings().embedding_dim
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "news_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "news_item_id",
            sa.Integer(),
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("embedding", Vector(dim), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "signal_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "signal_id",
            sa.Integer(),
            sa.ForeignKey("signals.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("embedding", Vector(dim), nullable=False),
        # A same-day re-run can rewrite a signal; the hash tells the embed step to refresh it.
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for table in ("news_embeddings", "signal_embeddings"):
        op.execute(
            f"CREATE INDEX ix_{table}_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)"
        )

    op.add_column(
        "pipeline_runs",
        sa.Column("embedding_tokens", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "embedding_tokens")
    op.drop_table("signal_embeddings")
    op.drop_table("news_embeddings")
    # The extension is left in place: other objects may use it.
