from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.calendar import category_service, link_service, schemas, service
from app.core.db import DbSession
from app.core.errors import ErrorResponse
from app.identity.dependencies import CurrentPrincipal

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

router = APIRouter(tags=["calendar"], responses=ERRORS)


@router.get("/calendar/items")
async def calendar_items(
    params: Annotated[schemas.CalendarParams, Query()],
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.CalendarItems:
    return await service.calendar_items(principal, db, params)


@router.get("/events")
async def list_events(
    params: Annotated[schemas.PeriodParams, Query()],
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.EventOccurrences:
    return await service.list_events(principal, db, params)


@router.post("/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: schemas.EventCreate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Event:
    return await service.create_event(principal, db, body)


@router.get("/events/{event_id}")
async def get_event(event_id: UUID, principal: CurrentPrincipal, db: DbSession) -> schemas.Event:
    return await service.get_event(principal, db, event_id)


@router.patch("/events/{event_id}")
async def update_event(
    event_id: UUID, body: schemas.EventUpdate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Event:
    return await service.update_event(principal, db, event_id, body)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: UUID, principal: CurrentPrincipal, db: DbSession) -> None:
    await service.delete_event(principal, db, event_id)


@router.delete("/events/{event_id}/participants/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_event(event_id: UUID, principal: CurrentPrincipal, db: DbSession) -> None:
    await service.leave_event(principal, db, event_id)


@router.get("/availability")
async def availability(
    params: Annotated[schemas.AvailabilityParams, Query()],
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.AvailabilityList:
    return await service.availability(principal, db, params)


@router.get("/search")
async def search(
    params: Annotated[schemas.SearchParams, Query()],
    principal: CurrentPrincipal,
    db: DbSession,
) -> schemas.SearchResults:
    return await service.search(principal, db, params)


@router.get("/categories")
async def list_categories(principal: CurrentPrincipal, db: DbSession) -> schemas.CategoryList:
    return await category_service.list_categories(principal, db)


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(
    body: schemas.CategoryCreate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Category:
    return await category_service.create_category(principal, db, body)


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: UUID, body: schemas.CategoryUpdate, principal: CurrentPrincipal, db: DbSession
) -> schemas.Category:
    return await category_service.update_category(principal, db, category_id, body)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: UUID, principal: CurrentPrincipal, db: DbSession) -> None:
    await category_service.delete_category(principal, db, category_id)


@router.post("/tasks/{task_id}/event-links", status_code=status.HTTP_204_NO_CONTENT)
async def link_task_to_event(
    task_id: UUID, body: schemas.EventLinkCreate, principal: CurrentPrincipal, db: DbSession
) -> None:
    await link_service.link_task(principal, db, task_id, body.event_id)


@router.delete("/tasks/{task_id}/event-links/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_task_from_event(
    task_id: UUID, event_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> None:
    await link_service.unlink_task(principal, db, task_id, event_id)
