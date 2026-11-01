"""benchmark returns

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable and additive, so the running API keeps working before and after.
    op.add_column("signals", sa.Column("benchmark_return_7d", sa.Float(), nullable=True))
    op.add_column("signals", sa.Column("benchmark_return_30d", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("signals", "benchmark_return_30d")
    op.drop_column("signals", "benchmark_return_7d")
