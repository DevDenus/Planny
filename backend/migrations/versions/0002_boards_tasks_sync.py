"""Boards, tasks, notifications, sync counters, and their rows for existing users

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")
POSITION = sa.Text(collation="C")
ACTIVITY_KINDS = (
    "created",
    "updated",
    "moved",
    "completed",
    "reopened",
    "assigned",
    "unassigned",
    "labeled",
    "unlabeled",
    "checklist_added",
    "checklist_checked",
    "checklist_unchecked",
    "checklist_removed",
    "event_linked",
    "event_unlinked",
)
NOTIFICATION_KINDS = (
    "event_added",
    "event_updated",
    "event_deleted",
    "event_removed",
    "event_reminder",
    "task_assigned",
    "task_updated",
    "task_commented",
    "task_due",
    "task_reminder",
    "board_added",
)


def timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )


def user_fk(column: str, table: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(
        column,
        sa.Uuid(),
        sa.ForeignKey("app_user.id", name=f"fk_{table}_{column}_app_user"),
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "board",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=False),
        sa.Column(
            "default_view", postgresql.ENUM("list", "kanban", name="board_view"), nullable=False
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        user_fk("created_by", "board"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index(
        "uq_board_personal_per_user",
        "board",
        ["created_by"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "board_member",
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("board.id", name="fk_board_member_board_id_board"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", name="fk_board_member_user_id_app_user"),
            primary_key=True,
        ),
        sa.Column(
            "role", postgresql.ENUM("owner", "editor", "viewer", name="board_role"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_board_member_user_id", "board_member", ["user_id"])
    op.create_table(
        "board_column",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("board.id", name="fk_board_column_board_id_board"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", POSITION, nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("board_id", "id", name="uq_board_column_board_id_id"),
    )
    op.create_table(
        "task",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("column_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("position", POSITION, nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        user_fk("created_by", "task"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["board_id", "column_id"],
            ["board_column.board_id", "board_column.id"],
            name="fk_task_board_id_board_column",
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 4", name="ck_task_priority_range"),
        sa.CheckConstraint(
            "NOT (due_date IS NOT NULL AND due_at IS NOT NULL)", name="ck_task_one_deadline"
        ),
    )
    op.create_index(
        "ix_task_board_id_column_id_position", "task", ["board_id", "column_id", "position"]
    )
    op.create_index(
        "uq_task_column_id_position",
        "task",
        ["column_id", "position"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_task_due_date", "task", ["due_date"])
    op.create_index("ix_task_due_at", "task", ["due_at"])
    op.create_table(
        "task_assignee",
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("task.id", name="fk_task_assignee_task_id_task"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", name="fk_task_assignee_user_id_app_user"),
            primary_key=True,
        ),
        user_fk("assigned_by", "task_assignee"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_task_assignee_user_id", "task_assignee", ["user_id"])
    op.create_table(
        "checklist_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("task.id", name="fk_checklist_item_task_id_task"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False),
        sa.Column("position", POSITION, nullable=False),
        *timestamps(),
        sa.UniqueConstraint("task_id", "position", name="uq_checklist_item_task_id_position"),
    )
    op.create_table(
        "task_activity",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("task.id", name="fk_task_activity_task_id_task"),
            nullable=False,
        ),
        user_fk("actor_id", "task_activity"),
        sa.Column("kind", postgresql.ENUM(*ACTIVITY_KINDS, name="activity_kind"), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_task_activity_task_id_id", "task_activity", ["task_id", sa.text("id DESC")])
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), primary_key=True),
        user_fk("user_id", "notification"),
        sa.Column(
            "kind", postgresql.ENUM(*NOTIFICATION_KINDS, name="notification_kind"), nullable=False
        ),
        user_fk("actor_id", "notification", nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("task.id", name="fk_notification_task_id_task"),
            nullable=True,
        ),
        sa.Column(
            "board_id",
            sa.Uuid(),
            sa.ForeignKey("board.id", name="fk_notification_board_id_board"),
            nullable=True,
        ),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_notification_dedupe_key"),
    )
    op.create_index(
        "ix_notification_user_id_created_at",
        "notification",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_notification_user_id_unread",
        "notification",
        ["user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_table(
        "sync_state",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", name="fk_sync_state_user_id_app_user"),
            primary_key=True,
        ),
        sa.Column(
            "scope",
            postgresql.ENUM("calendar", "tasks", "notifications", name="sync_scope"),
            primary_key=True,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False),
    )

    # Users created at stage 1 get what create_user now gives every new user.
    op.execute(
        """
        WITH personal AS (
            INSERT INTO board (id, name, icon, default_view, is_default, created_by, version)
            SELECT uuidv7(), 'Личная доска', 'inbox', 'list', true, id, 1 FROM app_user
            RETURNING id, created_by
        ), columns AS (
            INSERT INTO board_column (id, board_id, name, position, is_done)
            SELECT uuidv7(), personal.id, c.name, c.position, c.is_done
            FROM personal
            CROSS JOIN (VALUES ('К выполнению', 'a0', false), ('Готово', 'a1', true))
                AS c (name, position, is_done)
        )
        INSERT INTO board_member (board_id, user_id, role)
        SELECT id, created_by, 'owner' FROM personal
        """
    )
    op.execute(
        """
        INSERT INTO sync_state (user_id, scope, version)
        SELECT app_user.id, scope, 0
        FROM app_user CROSS JOIN unnest(enum_range(NULL::sync_scope)) AS scope
        """
    )


def downgrade() -> None:
    for table in (
        "sync_state",
        "notification",
        "task_activity",
        "checklist_item",
        "task_assignee",
        "task",
        "board_column",
        "board_member",
        "board",
    ):
        op.drop_table(table)
    for enum in (
        "sync_scope",
        "notification_kind",
        "activity_kind",
        "board_role",
        "board_view",
    ):
        op.execute(f"DROP TYPE {enum}")
