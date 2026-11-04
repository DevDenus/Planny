from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import ErrorResponse
from app.identity.dependencies import CurrentPrincipal
from app.tasks import board_service, schemas, task_service

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
    principal: CurrentPrincipal, db: DbSession, archived: bool = False
) -> schemas.BoardList:
    return await board_service.list_boards(principal, db, archived=archived)


@boards.post("", status_code=status.HTTP_201_CREATED)
async def create_board(
    body: schemas.BoardCreate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Board:
    return await board_service.create_board(principal, db, body)


@boards.get("/{board_id}")
async def get_board(board_id: UUID, principal: CurrentPrincipal, db: DbSession) -> schemas.Board:
    return await board_service.get_board(principal, db, board_id)


@boards.patch("/{board_id}")
async def update_board(
    board_id: UUID, body: schemas.BoardUpdate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Board:
    return await board_service.update_board(principal, db, board_id, body)


@boards.get("/{board_id}/columns")
async def list_columns(
    board_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> schemas.BoardColumnList:
    return await board_service.list_columns(principal, db, board_id)


@boards.get("/{board_id}/members")
async def list_members(
    board_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> schemas.BoardMemberList:
    return await board_service.list_members(principal, db, board_id)


@boards.post("/{board_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    board_id: UUID,
    body: schemas.BoardMemberCreate,
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.BoardMember:
    return await board_service.add_member(principal, db, board_id, body)


@boards.patch("/{board_id}/members/{user_id}")
async def update_member(
    board_id: UUID,
    user_id: UUID,
    body: schemas.BoardMemberUpdate,
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.BoardMember:
    return await board_service.update_member(principal, db, board_id, user_id, body)


@boards.delete("/{board_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    board_id: UUID, user_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> None:
    await board_service.remove_member(principal, db, board_id, user_id)


@tasks.get("")
async def list_tasks(
    filters: Annotated[schemas.TaskFilters, Query()], principal: CurrentPrincipal, db: DbSession
) -> schemas.TaskPage:
    return await task_service.list_tasks(principal, db, filters)


@tasks.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    body: schemas.TaskCreate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Task:
    return await task_service.create_task(principal, db, body)


@tasks.get("/{task_id}")
async def get_task(task_id: UUID, principal: CurrentPrincipal, db: DbSession) -> schemas.Task:
    return await task_service.get_task(principal, db, task_id)


@tasks.patch("/{task_id}")
async def update_task(
    task_id: UUID, body: schemas.TaskUpdate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Task:
    return await task_service.update_task(principal, db, task_id, body)


@tasks.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, principal: CurrentPrincipal, db: DbSession) -> None:
    await task_service.delete_task(principal, db, task_id)


@tasks.post("/{task_id}/move")
async def move_task(
    task_id: UUID, body: schemas.TaskMove, principal: CurrentPrincipal, db: DbSession
) -> schemas.Task:
    return await task_service.move_task(principal, db, task_id, body)


@tasks.post("/{task_id}/complete")
async def complete_task(task_id: UUID, principal: CurrentPrincipal, db: DbSession) -> schemas.Task:
    return await task_service.complete_task(principal, db, task_id)


@tasks.post("/{task_id}/reopen")
async def reopen_task(task_id: UUID, principal: CurrentPrincipal, db: DbSession) -> schemas.Task:
    return await task_service.reopen_task(principal, db, task_id)


@tasks.post("/{task_id}/checklist", status_code=status.HTTP_201_CREATED)
async def add_checklist_item(
    task_id: UUID,
    body: schemas.ChecklistItemCreate,
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.ChecklistItem:
    return await task_service.add_checklist_item(principal, db, task_id, body)


@tasks.patch("/{task_id}/checklist/{item_id}")
async def update_checklist_item(
    task_id: UUID,
    item_id: UUID,
    body: schemas.ChecklistItemUpdate,
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.ChecklistItem:
    return await task_service.update_checklist_item(principal, db, task_id, item_id, body)


@tasks.delete("/{task_id}/checklist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist_item(
    task_id: UUID, item_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> None:
    await task_service.delete_checklist_item(principal, db, task_id, item_id)
