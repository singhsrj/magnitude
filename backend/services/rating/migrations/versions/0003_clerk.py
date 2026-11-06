"""attach players to Clerk accounts

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: anonymous players have none. A unique constraint on a nullable column allows many NULLs
    # in Postgres and SQLite, and at most one player per Clerk account.
    with op.batch_alter_table("players") as batch:
        batch.add_column(sa.Column("clerk_user_id", sa.String(128), nullable=True))
        batch.create_unique_constraint("uq_players_clerk_user_id", ["clerk_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("players") as batch:
        batch.drop_constraint("uq_players_clerk_user_id", type_="unique")
        batch.drop_column("clerk_user_id")
