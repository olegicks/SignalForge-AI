"""ask requests log

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Backs the daily cap and cost tracking for POST /ask. The question text itself is not
    # stored, and the client IP only as a hash.
    op.create_table(
        "ask_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("ticker", sa.String(16), nullable=True),
        sa.Column("retrieved_count", sa.Integer(), nullable=False),
        sa.Column("sufficient_evidence", sa.Boolean(), nullable=False),
        sa.Column("embedding_tokens", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("est_cost_usd", sa.Numeric(12, 6), nullable=False),
    )
    op.create_index("ix_ask_requests_created_at", "ask_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ask_requests_created_at", table_name="ask_requests")
    op.drop_table("ask_requests")
