from typing import Annotated, Any

from fastapi import APIRouter, Header, status

from app.core.db import DbSession
from app.core.errors import ErrorResponse
from app.identity import schemas, service
from app.identity.dependencies import (
    AnyCaller,
    BffOnly,
    CurrentCaller,
    CurrentSession,
    PendingSession,
)

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
ACCESS_ERRORS: dict[int | str, dict[str, Any]] = {
    **ERRORS,
    403: {"model": ErrorResponse},
}

router = APIRouter()


@router.post(
    "/auth/login",
    tags=["auth"],
    responses={**ERRORS, 429: {"model": ErrorResponse}},
)
async def login(
    body: schemas.LoginRequest,
    db: DbSession,
    bff: BffOnly,
    user_agent: Annotated[str | None, Header()] = None,
) -> schemas.LoginResponse:
    result = await service.login(
        db,
        login=body.login,
        password=body.password,
        ip=bff.client_ip,
        user_agent=user_agent,
    )
    return schemas.LoginResponse(
        token=result.token,
        expires_at=result.expires_at,
        user=schemas.CurrentUser.model_validate(result.user),
    )


@router.post(
    "/auth/logout", tags=["auth"], status_code=status.HTTP_204_NO_CONTENT, responses=ACCESS_ERRORS
)
async def logout(principal: PendingSession, db: DbSession) -> None:
    await service.logout(principal, db)


@router.post(
    "/auth/change-password",
    tags=["auth"],
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ACCESS_ERRORS,
)
async def change_password(
    body: schemas.ChangePasswordRequest, principal: PendingSession, db: DbSession
) -> None:
    await service.change_password(
        principal,
        db,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.get("/me", tags=["profile"], responses=ERRORS)
async def get_me(principal: AnyCaller, db: DbSession) -> schemas.CurrentUser:
    return schemas.CurrentUser.model_validate(await service.get_current_user(principal, db))


@router.patch("/me", tags=["profile"], responses=ACCESS_ERRORS)
async def update_me(
    body: schemas.UpdateProfileRequest, principal: CurrentSession, db: DbSession
) -> schemas.CurrentUser:
    user = await service.update_profile(principal, db, **body.model_dump(exclude_none=True))
    return schemas.CurrentUser.model_validate(user)


@router.get("/users", tags=["profile"], responses=ACCESS_ERRORS)
async def list_users(principal: CurrentCaller, db: DbSession) -> schemas.UserList:
    users = await service.list_active_users(principal, db)
    return schemas.UserList(items=[schemas.UserSummary.model_validate(u) for u in users])
