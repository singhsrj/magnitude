"""practice sessions for offline play + background sync (Phase 4)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),  # uint32 does not fit a signed int4
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gen_skills", json_type, nullable=True),  # set by round 0
        sa.Column("next_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_sum_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),  # open | broken
    )
    op.create_index("ix_sessions_player", "sessions", ["player_id", "issued_at"])

    op.add_column("players", sa.Column("imported", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column("rounds", sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True))
    op.add_column("rounds", sa.Column("round_index", sa.Integer(), nullable=True))
    op.create_index(
        "uq_rounds_session",
        "rounds",
        ["session_id", "round_index"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_rounds_session", table_name="rounds")
    op.drop_column("rounds", "round_index")
    op.drop_column("rounds", "session_id")
    op.drop_column("players", "imported")
    op.drop_index("ix_sessions_player", table_name="sessions")
    op.drop_table("sessions")
