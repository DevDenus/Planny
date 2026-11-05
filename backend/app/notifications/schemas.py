from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.identity.schemas import UserSummary
from app.notifications.models import NotificationKind


class Notification(BaseModel):
    id: UUID
    kind: NotificationKind
    title: str
    actor: UserSummary | None
    event_id: UUID | None
    task_id: UUID | None
    board_id: UUID | None
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[Notification]
    next_cursor: str | None


class SyncState(BaseModel):
    calendar: int
    tasks: int
    notifications: int
    unread_notifications: int
