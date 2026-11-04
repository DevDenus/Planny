from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import forbidden, id_conflict, not_found
from app.core.pagination import (
    decode_cursor,
    encode_cursor,
    invalid_cursor,
    parse_id,
    parse_moment,
)
from app.core.principal import Principal
from app.identity import service as identity
from app.identity.schemas import UserSummary
from app.notifications import service as notifications
from app.notifications.models import NotificationKind
from app.tasks import board_service, models, repository, schemas, task_service
from app.tasks.models import BoardRole


async def _comments_out(
    db: AsyncSession, comments: Sequence[models.TaskComment]
) -> list[schemas.TaskComment]:
    users = await identity.users_by_id(db, {comment.author_id for comment in comments})
    return [
        schemas.TaskComment(
            id=comment.id,
            author=UserSummary.model_validate(users[comment.author_id]),
            body=comment.body,
            created_at=comment.created_at,
            edited_at=comment.edited_at,
        )
        for comment in comments
    ]


def _parse_comment_cursor(cursor: str) -> tuple[datetime, UUID]:
    values = decode_cursor(cursor)
    if len(values) != 2:
        raise invalid_cursor()
    return parse_moment(values[0]), parse_id(values[1])


async def list_comments(
    principal: Principal, db: AsyncSession, task_id: UUID, params: schemas.PageParams
) -> schemas.TaskCommentPage:
    await task_service.readable(principal, db, task_id)
    after = _parse_comment_cursor(params.cursor) if params.cursor else None
    rows = await repository.list_comments(db, task_id, limit=params.limit + 1, after=after)
    page = rows[: params.limit]
    next_cursor = None
    if len(rows) > params.limit:
        next_cursor = encode_cursor([page[-1].created_at.isoformat(), str(page[-1].id)])
    return schemas.TaskCommentPage(items=await _comments_out(db, page), next_cursor=next_cursor)


async def _recipients(db: AsyncSession, task: models.Task) -> set[UUID]:
    """Someone who left the board keeps old comments but no longer sees the card."""
    interested = set(await repository.assignee_ids(db, task.id))
    interested |= set(await repository.commenter_ids(db, task.id))
    return interested & set(await repository.member_ids(db, task.board_id))


async def add_comment(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.TaskCommentCreate
) -> schemas.TaskComment:
    task, _ = await task_service.locked_writable(principal, db, task_id)
    if body.id is not None:
        repeated = await repository.get_comment(db, body.id)
        if repeated is not None:
            mine = repeated.task_id == task.id and repeated.author_id == principal.user_id
            if not mine or repeated.deleted_at is not None:
                raise id_conflict()
            return (await _comments_out(db, [repeated]))[0]

    recipients = await _recipients(db, task)
    comment = models.TaskComment(task_id=task.id, author_id=principal.user_id, body=body.body)
    if body.id is not None:
        comment.id = body.id
    db.add(comment)
    notified = notifications.notify(
        db,
        recipients,
        NotificationKind.task_commented,
        actor_id=principal.user_id,
        title=task.title,
        task_id=task.id,
        board_id=task.board_id,
    )
    await board_service.publish(db, task.board_id, notified=notified)
    created = (await _comments_out(db, [comment]))[0]
    await db.commit()
    return created


async def _comment_of(
    db: AsyncSession, task: models.Task, comment_id: UUID
) -> models.TaskComment | None:
    comment = await repository.get_comment(db, comment_id)
    if comment is None or comment.task_id != task.id or comment.deleted_at is not None:
        return None
    return comment


async def update_comment(
    principal: Principal,
    db: AsyncSession,
    task_id: UUID,
    comment_id: UUID,
    body: schemas.TaskCommentUpdate,
) -> schemas.TaskComment:
    task, _ = await task_service.locked_writable(principal, db, task_id)
    comment = await _comment_of(db, task, comment_id)
    if comment is None:
        raise not_found()
    if comment.author_id != principal.user_id:
        raise forbidden("Изменить можно только свой комментарий")
    if comment.body != body.body:
        comment.body = body.body
        comment.edited_at = utcnow()
        await board_service.publish(db, task.board_id)
    updated = (await _comments_out(db, [comment]))[0]
    await db.commit()
    return updated


async def delete_comment(
    principal: Principal, db: AsyncSession, task_id: UUID, comment_id: UUID
) -> None:
    task, target = await task_service.locked_writable(principal, db, task_id)
    comment = await _comment_of(db, task, comment_id)
    if comment is None:
        return
    if comment.author_id != principal.user_id and target.role != BoardRole.owner:
        raise forbidden("Удалить чужой комментарий может только владелец доски")
    comment.deleted_at = utcnow()
    await board_service.publish(db, task.board_id)
    await db.commit()


def _parse_activity_cursor(cursor: str) -> int:
    values = decode_cursor(cursor)
    if len(values) != 1 or type(values[0]) is not int:
        raise invalid_cursor()
    return values[0]


async def list_activity(
    principal: Principal, db: AsyncSession, task_id: UUID, params: schemas.PageParams
) -> schemas.TaskActivityPage:
    await task_service.readable(principal, db, task_id)
    before = _parse_activity_cursor(params.cursor) if params.cursor else None
    rows = await repository.list_activity(db, task_id, limit=params.limit + 1, before=before)
    page = rows[: params.limit]
    users = await identity.users_by_id(db, {row.actor_id for row in page})
    return schemas.TaskActivityPage(
        items=[
            schemas.TaskActivity(
                id=row.id,
                kind=row.kind,
                actor=UserSummary.model_validate(users[row.actor_id]),
                data=row.data,
                created_at=row.created_at,
            )
            for row in page
        ],
        next_cursor=encode_cursor([page[-1].id]) if len(rows) > params.limit else None,
    )
