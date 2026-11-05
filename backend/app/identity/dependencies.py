import ipaddress
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.db import DbSession
from app.core.errors import (
    field_error,
    insufficient_scope,
    password_change_required,
    unauthorized,
)
from app.core.principal import Principal, Scope
from app.identity import service

bearer_scheme = HTTPBearer(auto_error=False)


async def get_caller(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    """Anyone with a valid token, before the password gate and any scope."""
    if credentials is None:
        raise unauthorized()
    return await service.authenticate(db, credentials.credentials)


async def get_pending_session(caller: Annotated[Principal, Depends(get_caller)]) -> Principal:
    """For the few routes a user must reach before replacing the one-time password."""
    if caller.kind != "session":
        raise insufficient_scope()
    return caller


async def get_session(session: Annotated[Principal, Depends(get_pending_session)]) -> Principal:
    if session.must_change_password:
        raise password_change_required()
    return session


def require_scopes(*required: Scope) -> Callable[..., Awaitable[Principal]]:
    """Opens a route to the keys that hold every scope listed. A session passes with any list."""

    async def check(caller: Annotated[Principal, Depends(get_caller)]) -> Principal:
        if caller.must_change_password:
            raise password_change_required()
        if not caller.allows(*required):
            raise insufficient_scope(required)
        return caller

    return check


# A route is closed to keys unless it asks for scopes, so forgetting them can't widen what a
# key reaches.
PendingSession = Annotated[Principal, Depends(get_pending_session)]
CurrentSession = Annotated[Principal, Depends(get_session)]

# Who the key is and who it can name. Neither says anything about events or tasks.
AnyCaller = Annotated[Principal, Depends(get_caller)]
CurrentCaller = Annotated[Principal, Depends(require_scopes())]

EventsRead = Annotated[Principal, Depends(require_scopes(Scope.events_read))]
EventsWrite = Annotated[Principal, Depends(require_scopes(Scope.events_write))]
AvailabilityRead = Annotated[Principal, Depends(require_scopes(Scope.availability_read))]
TasksRead = Annotated[Principal, Depends(require_scopes(Scope.tasks_read))]
TasksWrite = Annotated[Principal, Depends(require_scopes(Scope.tasks_write))]
NotificationsRead = Annotated[Principal, Depends(require_scopes(Scope.notifications_read))]

# For the routes that touch both sides at once.
EventsAndTasksRead = Annotated[
    Principal, Depends(require_scopes(Scope.events_read, Scope.tasks_read))
]
EventsAndTasksWrite = Annotated[
    Principal, Depends(require_scopes(Scope.events_write, Scope.tasks_write))
]


@dataclass(frozen=True, slots=True)
class BffCall:
    client_ip: str


async def require_bff(
    x_bff_secret: Annotated[str | None, Header()] = None,
    x_client_ip: Annotated[str | None, Header()] = None,
) -> BffCall:
    """Keeps password guessing away from the LAN port: login goes only through the BFF."""
    expected = get_settings().bff_shared_secret
    if (
        expected is None
        or x_bff_secret is None
        or not secrets.compare_digest(x_bff_secret.encode(), expected.get_secret_value().encode())
    ):
        raise unauthorized()
    try:
        return BffCall(client_ip=str(ipaddress.ip_address(x_client_ip or "")))
    except ValueError:
        raise field_error("x-client-ip", "Неверный адрес") from None


BffOnly = Annotated[BffCall, Depends(require_bff)]
