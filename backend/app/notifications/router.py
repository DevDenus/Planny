from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.core.db import DbSession
from app.core.errors import ErrorResponse
from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.identity.dependencies import CurrentPrincipal
from app.notifications import schemas, service

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
NOT_FOUND_ERRORS: dict[int | str, dict[str, Any]] = {**ERRORS, 404: {"model": ErrorResponse}}

router = APIRouter(tags=["notifications"])


@router.get("/notifications", responses=ERRORS)
async def list_notifications(
    principal: CurrentPrincipal,
    db: DbSession,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> schemas.NotificationPage:
    return await service.list_notifications(
        principal, db, unread_only=unread_only, limit=limit, cursor=cursor
    )


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def read_all_notifications(principal: CurrentPrincipal, db: DbSession) -> None:
    await service.read_all(principal, db)


@router.post(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND_ERRORS,
)
async def read_notification(
    notification_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> None:
    await service.read_notification(principal, db, notification_id)


@router.get("/sync", tags=["sync"], responses=ERRORS)
async def get_sync(principal: CurrentPrincipal, db: DbSession) -> schemas.SyncState:
    return await service.sync_state(principal, db)
