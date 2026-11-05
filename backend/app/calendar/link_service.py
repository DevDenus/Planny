from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import repository
from app.calendar.models import Event
from app.core.errors import not_found
from app.core.principal import Principal
from app.tasks import board_service, models, task_service
from app.tasks import repository as tasks_repository
from app.tasks.models import ActivityKind


async def _own_event(principal: Principal, db: AsyncSession, event_id: UUID) -> Event:
    event = await repository.get_event(db, event_id)
    mine = await repository.get_participant(db, event_id, principal.user_id)
    if event is None or mine is None:
        raise not_found()
    return event


async def _publish(
    principal: Principal, db: AsyncSession, task: models.Task, event: Event, kind: ActivityKind
) -> None:
    tasks_repository.add_activity(
        db, task.id, principal.user_id, kind, {"event_id": str(event.id), "title": event.title}
    )
    participants = await repository.participant_ids(db, event.id)
    await board_service.publish(db, task.board_id, calendar_for=participants)
    await db.commit()


async def link_task(principal: Principal, db: AsyncSession, task_id: UUID, event_id: UUID) -> None:
    task, _ = await task_service.locked_writable(principal, db, task_id)
    event = await _own_event(principal, db, event_id)
    if event.deleted_at is not None:
        raise not_found()
    if await repository.add_link(db, task.id, event.id):
        await _publish(principal, db, task, event, ActivityKind.event_linked)


async def unlink_task(
    principal: Principal, db: AsyncSession, task_id: UUID, event_id: UUID
) -> None:
    task, _ = await task_service.locked_writable(principal, db, task_id)
    event = await _own_event(principal, db, event_id)
    if await repository.remove_link(db, task.id, event.id):
        await _publish(principal, db, task, event, ActivityKind.event_unlinked)
