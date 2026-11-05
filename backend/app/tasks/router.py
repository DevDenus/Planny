from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import ErrorResponse
from app.identity.dependencies import TasksRead, TasksWrite
from app.tasks import (
    board_service,
    column_service,
    comment_service,
    label_service,
    schemas,
    task_service,
)

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

boards = APIRouter(prefix="/boards", tags=["boards"], responses=ERRORS)
tasks = APIRouter(prefix="/tasks", tags=["tasks"], responses=ERRORS)


@boards.get("")
async def list_boards(
    principal: TasksRead, db: DbSession, archived: bool = False
) -> schemas.BoardList:
    return await board_service.list_boards(principal, db, archived=archived)


@boards.post("", status_code=status.HTTP_201_CREATED)
async def create_board(
    body: schemas.BoardCreate, principal: TasksWrite, db: DbSession
) -> schemas.Board:
    return await board_service.create_board(principal, db, body)


@boards.get("/{board_id}")
async def get_board(board_id: UUID, principal: TasksRead, db: DbSession) -> schemas.Board:
    return await board_service.get_board(principal, db, board_id)


@boards.patch("/{board_id}")
async def update_board(
    board_id: UUID, body: schemas.BoardUpdate, principal: TasksWrite, db: DbSession
) -> schemas.Board:
    return await board_service.update_board(principal, db, board_id, body)


@boards.get("/{board_id}/columns")
async def list_columns(
    board_id: UUID, principal: TasksRead, db: DbSession
) -> schemas.BoardColumnList:
    return await board_service.list_columns(principal, db, board_id)


@boards.post("/{board_id}/columns", status_code=status.HTTP_201_CREATED)
async def create_column(
    board_id: UUID, body: schemas.BoardColumnCreate, principal: TasksWrite, db: DbSession
) -> schemas.BoardColumn:
    return await column_service.create_column(principal, db, board_id, body)


@boards.patch("/{board_id}/columns/{column_id}")
async def update_column(
    board_id: UUID,
    column_id: UUID,
    body: schemas.BoardColumnUpdate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.BoardColumn:
    return await column_service.update_column(principal, db, board_id, column_id, body)


@boards.post("/{board_id}/columns/{column_id}/move")
async def move_column(
    board_id: UUID,
    column_id: UUID,
    body: schemas.BoardColumnMove,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.BoardColumn:
    return await column_service.move_column(principal, db, board_id, column_id, body)


@boards.delete("/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(
    board_id: UUID,
    column_id: UUID,
    principal: TasksWrite,
    db: DbSession,
    move_to: UUID | None = None,
) -> None:
    await column_service.delete_column(principal, db, board_id, column_id, move_to)


@boards.get("/{board_id}/labels")
async def list_labels(board_id: UUID, principal: TasksRead, db: DbSession) -> schemas.LabelList:
    return await label_service.list_labels(principal, db, board_id)


@boards.post("/{board_id}/labels", status_code=status.HTTP_201_CREATED)
async def create_label(
    board_id: UUID, body: schemas.LabelCreate, principal: TasksWrite, db: DbSession
) -> schemas.Label:
    return await label_service.create_label(principal, db, board_id, body)


@boards.patch("/{board_id}/labels/{label_id}")
async def update_label(
    board_id: UUID,
    label_id: UUID,
    body: schemas.LabelUpdate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.Label:
    return await label_service.update_label(principal, db, board_id, label_id, body)


@boards.delete("/{board_id}/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(
    board_id: UUID, label_id: UUID, principal: TasksWrite, db: DbSession
) -> None:
    await label_service.delete_label(principal, db, board_id, label_id)


@boards.get("/{board_id}/members")
async def list_members(
    board_id: UUID, principal: TasksRead, db: DbSession
) -> schemas.BoardMemberList:
    return await board_service.list_members(principal, db, board_id)


@boards.post("/{board_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    board_id: UUID,
    body: schemas.BoardMemberCreate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.BoardMember:
    return await board_service.add_member(principal, db, board_id, body)


@boards.patch("/{board_id}/members/{user_id}")
async def update_member(
    board_id: UUID,
    user_id: UUID,
    body: schemas.BoardMemberUpdate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.BoardMember:
    return await board_service.update_member(principal, db, board_id, user_id, body)


@boards.delete("/{board_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    board_id: UUID, user_id: UUID, principal: TasksWrite, db: DbSession
) -> None:
    await board_service.remove_member(principal, db, board_id, user_id)


@tasks.get("")
async def list_tasks(
    filters: Annotated[schemas.TaskFilters, Query()], principal: TasksRead, db: DbSession
) -> schemas.TaskPage:
    return await task_service.list_tasks(principal, db, filters)


@tasks.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    body: schemas.TaskCreate, principal: TasksWrite, db: DbSession
) -> schemas.Task:
    return await task_service.create_task(principal, db, body)


@tasks.get("/{task_id}")
async def get_task(task_id: UUID, principal: TasksRead, db: DbSession) -> schemas.Task:
    return await task_service.get_task(principal, db, task_id)


@tasks.patch("/{task_id}")
async def update_task(
    task_id: UUID, body: schemas.TaskUpdate, principal: TasksWrite, db: DbSession
) -> schemas.Task:
    return await task_service.update_task(principal, db, task_id, body)


@tasks.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, principal: TasksWrite, db: DbSession) -> None:
    await task_service.delete_task(principal, db, task_id)


@tasks.post("/{task_id}/move")
async def move_task(
    task_id: UUID, body: schemas.TaskMove, principal: TasksWrite, db: DbSession
) -> schemas.Task:
    return await task_service.move_task(principal, db, task_id, body)


@tasks.post("/{task_id}/complete")
async def complete_task(task_id: UUID, principal: TasksWrite, db: DbSession) -> schemas.Task:
    return await task_service.complete_task(principal, db, task_id)


@tasks.post("/{task_id}/reopen")
async def reopen_task(task_id: UUID, principal: TasksWrite, db: DbSession) -> schemas.Task:
    return await task_service.reopen_task(principal, db, task_id)


@tasks.post("/{task_id}/checklist", status_code=status.HTTP_201_CREATED)
async def add_checklist_item(
    task_id: UUID,
    body: schemas.ChecklistItemCreate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.ChecklistItem:
    return await task_service.add_checklist_item(principal, db, task_id, body)


@tasks.patch("/{task_id}/checklist/{item_id}")
async def update_checklist_item(
    task_id: UUID,
    item_id: UUID,
    body: schemas.ChecklistItemUpdate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.ChecklistItem:
    return await task_service.update_checklist_item(principal, db, task_id, item_id, body)


@tasks.delete("/{task_id}/checklist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist_item(
    task_id: UUID, item_id: UUID, principal: TasksWrite, db: DbSession
) -> None:
    await task_service.delete_checklist_item(principal, db, task_id, item_id)


@tasks.get("/{task_id}/comments")
async def list_comments(
    task_id: UUID,
    params: Annotated[schemas.PageParams, Query()],
    principal: TasksRead,
    db: DbSession,
) -> schemas.TaskCommentPage:
    return await comment_service.list_comments(principal, db, task_id, params)


@tasks.post("/{task_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    task_id: UUID,
    body: schemas.TaskCommentCreate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.TaskComment:
    return await comment_service.add_comment(principal, db, task_id, body)


@tasks.patch("/{task_id}/comments/{comment_id}")
async def update_comment(
    task_id: UUID,
    comment_id: UUID,
    body: schemas.TaskCommentUpdate,
    principal: TasksWrite,
    db: DbSession,
) -> schemas.TaskComment:
    return await comment_service.update_comment(principal, db, task_id, comment_id, body)


@tasks.delete("/{task_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    task_id: UUID, comment_id: UUID, principal: TasksWrite, db: DbSession
) -> None:
    await comment_service.delete_comment(principal, db, task_id, comment_id)


@tasks.get("/{task_id}/activity")
async def list_activity(
    task_id: UUID,
    params: Annotated[schemas.PageParams, Query()],
    principal: TasksRead,
    db: DbSession,
) -> schemas.TaskActivityPage:
    return await comment_service.list_activity(principal, db, task_id, params)
