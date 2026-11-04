"""Labels, comments, and one key per column position

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_board_column_board_id_position", "board_column", ["board_id", "position"]
    )
    op.create_table(
        "board_label",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("board.id", name="fk_board_label_board_id_board"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("board_id", "name", name="uq_board_label_board_id_name"),
    )
    op.create_table(
        "task_label",
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("task.id", name="fk_task_label_task_id_task"),
            primary_key=True,
        ),
        sa.Column(
            "label_id",
            sa.Uuid(),
            sa.ForeignKey("board_label.id", name="fk_task_label_label_id_board_label"),
            primary_key=True,
        ),
    )
    op.create_index("ix_task_label_label_id", "task_label", ["label_id"])
    op.create_table(
        "task_comment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("task.id", name="fk_task_comment_task_id_task"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", name="fk_task_comment_author_id_app_user"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_task_comment_task_id_created_at", "task_comment", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_table("task_comment")
    op.drop_table("task_label")
    op.drop_table("board_label")
    op.drop_constraint("uq_board_column_board_id_position", "board_column", type_="unique")
