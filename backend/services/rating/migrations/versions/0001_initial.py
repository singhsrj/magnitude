"""initial schema: players, rounds, daily_results

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("peak", sa.Float(), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("best_streak", sa.Integer(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("skills", json_type, nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_players_token_hash"),
    )

    op.create_table(
        "rounds",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("skill", sa.String(16), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("rating_after", sa.Float(), nullable=False),
        sa.Column("problem_rating", sa.Integer(), nullable=False),
        sa.Column("problem_id", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("daily_index", sa.SmallInteger(), nullable=True),
    )
    op.create_index("ix_rounds_player_at", "rounds", ["player_id", "at"])
    op.create_index("ix_rounds_player_local_date", "rounds", ["player_id", "local_date"])
    op.create_index(
        "uq_rounds_daily",
        "rounds",
        ["player_id", "local_date", "daily_index"],
        unique=True,
        postgresql_where=sa.text("mode = 'daily'"),
    )

    op.create_table(
        "daily_results",
        sa.Column("player_id", sa.Uuid(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_results")
    op.drop_index("uq_rounds_daily", table_name="rounds")
    op.drop_index("ix_rounds_player_local_date", table_name="rounds")
    op.drop_index("ix_rounds_player_at", table_name="rounds")
    op.drop_table("rounds")
    op.drop_table("players")
