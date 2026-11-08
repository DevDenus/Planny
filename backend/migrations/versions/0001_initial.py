"""Initial schema: identity, calendar, tasks, reminders, notifications

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("active", "blocked", name="user_status"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("login = lower(login)", name=op.f("ck_app_user_login_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("login", name=op.f("uq_app_user_login")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_table(
        "login_attempt",
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("login", "ip", name=op.f("pk_login_attempt")),
    )
    op.create_table(
        "api_key",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_api_key_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_key")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_key_key_hash")),
    )
    op.create_index("ix_api_key_user_id", "api_key", ["user_id"], unique=False)
    op.create_table(
        "board",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=False),
        sa.Column("default_view", sa.Enum("list", "kanban", name="board_view"), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app_user.id"], name=op.f("fk_board_created_by_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board")),
    )
    op.create_index(
        "uq_board_personal_per_user",
        "board",
        ["created_by"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        sa.Column("series_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(all_day AND start_date IS NOT NULL AND end_date IS NOT NULL"
            " AND end_date >= start_date AND start_at IS NULL AND end_at IS NULL)"
            " OR (NOT all_day AND start_at IS NOT NULL AND end_at IS NOT NULL"
            " AND end_at > start_at AND start_date IS NULL AND end_date IS NULL)",
            name=op.f("ck_event_time_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app_user.id"], name=op.f("fk_event_created_by_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event")),
    )
    op.create_index("ix_event_series_end_at", "event", ["series_end_at"], unique=False)
    op.create_table(
        "event_category",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_event_category_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_category")),
        sa.UniqueConstraint("user_id", "id", name=op.f("uq_event_category_user_id_id")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_event_category_user_id_name")),
    )
    op.create_table(
        "session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_session_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_session_token_hash")),
    )
    op.create_index("ix_session_user_id", "session", ["user_id"], unique=False)
    op.create_table(
        "sync_state",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum("calendar", "tasks", "notifications", name="sync_scope"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_sync_state_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("user_id", "scope", name=op.f("pk_sync_state")),
    )
    op.create_table(
        "board_column",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Text(collation="C"), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"], ["board.id"], name=op.f("fk_board_column_board_id_board")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_column")),
        sa.UniqueConstraint("board_id", "id", name=op.f("uq_board_column_board_id_id")),
        sa.UniqueConstraint("board_id", "position", name=op.f("uq_board_column_board_id_position")),
    )
    op.create_table(
        "board_label",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"], ["board.id"], name=op.f("fk_board_label_board_id_board")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_board_label")),
        sa.UniqueConstraint("board_id", "name", name=op.f("uq_board_label_board_id_name")),
    )
    op.create_table(
        "board_member",
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Enum("owner", "editor", "viewer", name="board_role"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["board_id"], ["board.id"], name=op.f("fk_board_member_board_id_board")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_board_member_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("board_id", "user_id", name=op.f("pk_board_member")),
    )
    op.create_index("ix_board_member_user_id", "board_member", ["user_id"], unique=False)
    op.create_table(
        "event_participant",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("added_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["added_by"], ["app_user.id"], name=op.f("fk_event_participant_added_by_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["event.id"], name=op.f("fk_event_participant_event_id_event")
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["event_category.user_id", "event_category.id"],
            name=op.f("fk_event_participant_user_id_event_category"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_event_participant_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("event_id", "user_id", name=op.f("pk_event_participant")),
    )
    op.create_index(
        "ix_event_participant_user_id_event_id",
        "event_participant",
        ["user_id", "event_id"],
        unique=False,
    )
    op.create_table(
        "task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("board_id", sa.Uuid(), nullable=False),
        sa.Column("column_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("position", sa.Text(collation="C"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT (due_date IS NOT NULL AND due_at IS NOT NULL)", name=op.f("ck_task_one_deadline")
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 4", name=op.f("ck_task_priority_range")),
        sa.ForeignKeyConstraint(
            ["board_id", "column_id"],
            ["board_column.board_id", "board_column.id"],
            name=op.f("fk_task_board_id_board_column"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app_user.id"], name=op.f("fk_task_created_by_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
    )
    op.create_index(
        "ix_task_board_id_column_id_position",
        "task",
        ["board_id", "column_id", "position"],
        unique=False,
    )
    op.create_index("ix_task_due_at", "task", ["due_at"], unique=False)
    op.create_index("ix_task_due_date", "task", ["due_date"], unique=False)
    op.create_index(
        "uq_task_column_id_position",
        "task",
        ["column_id", "position"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "checklist_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Text(collation="C"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_checklist_item_task_id_task")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_item")),
        sa.UniqueConstraint("task_id", "position", name=op.f("uq_checklist_item_task_id_position")),
    )
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
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
                name="notification_kind",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("board_id", sa.Uuid(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["app_user.id"], name=op.f("fk_notification_actor_id_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["board_id"], ["board.id"], name=op.f("fk_notification_board_id_board")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["event.id"], name=op.f("fk_notification_event_id_event")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_notification_task_id_task")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_notification_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notification_dedupe_key")),
    )
    op.create_index(
        "ix_notification_user_id_created_at",
        "notification",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_notification_user_id_unread",
        "notification",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_table(
        "reminder",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("minutes_before", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(event_id IS NOT NULL AND minutes_before IS NOT NULL AND task_id IS NULL"
            " AND remind_at IS NULL)"
            " OR (task_id IS NOT NULL AND remind_at IS NOT NULL AND event_id IS NULL"
            " AND minutes_before IS NULL)",
            name=op.f("ck_reminder_target_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["event.id"], name=op.f("fk_reminder_event_id_event")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_reminder_task_id_task")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_reminder_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder")),
        sa.UniqueConstraint(
            "user_id",
            "event_id",
            "minutes_before",
            name=op.f("uq_reminder_user_id_event_id_minutes_before"),
        ),
        sa.UniqueConstraint("user_id", "task_id", name=op.f("uq_reminder_user_id_task_id")),
    )
    op.create_index("ix_reminder_event_id", "reminder", ["event_id"], unique=False)
    op.create_index(
        "ix_reminder_next_fire_at",
        "reminder",
        ["next_fire_at"],
        unique=False,
        postgresql_where=sa.text("next_fire_at IS NOT NULL"),
    )
    op.create_table(
        "task_activity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
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
                name="activity_kind",
            ),
            nullable=False,
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["app_user.id"], name=op.f("fk_task_activity_actor_id_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_task_activity_task_id_task")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_activity")),
    )
    op.create_index(
        "ix_task_activity_task_id_id",
        "task_activity",
        ["task_id", sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_table(
        "task_assignee",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["app_user.id"], name=op.f("fk_task_assignee_assigned_by_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_task_assignee_task_id_task")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_task_assignee_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("task_id", "user_id", name=op.f("pk_task_assignee")),
    )
    op.create_index("ix_task_assignee_user_id", "task_assignee", ["user_id"], unique=False)
    op.create_table(
        "task_comment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["app_user.id"], name=op.f("fk_task_comment_author_id_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_task_comment_task_id_task")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_comment")),
    )
    op.create_index(
        "ix_task_comment_task_id_created_at",
        "task_comment",
        ["task_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "task_event_link",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["event.id"], name=op.f("fk_task_event_link_event_id_event")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["task.id"], name=op.f("fk_task_event_link_task_id_task")
        ),
        sa.PrimaryKeyConstraint("task_id", "event_id", name=op.f("pk_task_event_link")),
    )
    op.create_index("ix_task_event_link_event_id", "task_event_link", ["event_id"], unique=False)
    op.create_table(
        "task_label",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("label_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["label_id"], ["board_label.id"], name=op.f("fk_task_label_label_id_board_label")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name=op.f("fk_task_label_task_id_task")),
        sa.PrimaryKeyConstraint("task_id", "label_id", name=op.f("pk_task_label")),
    )
    op.create_index("ix_task_label_label_id", "task_label", ["label_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Migrations go forward only; roll back by restoring a backup")
