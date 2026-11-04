import ipaddress
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.db import DbSession
from app.core.errors import field_error, password_change_required, unauthorized
from app.core.principal import Principal
from app.identity import service

bearer_scheme = HTTPBearer(auto_error=False)


async def get_principal_pending_password(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    """For the few routes a user must reach before replacing the one-time password."""
    if credentials is None:
        raise unauthorized()
    return await service.authenticate(db, credentials.credentials)


async def get_principal(
    principal: Annotated[Principal, Depends(get_principal_pending_password)],
) -> Principal:
    if principal.must_change_password:
        raise password_change_required()
    return principal


AnyPrincipal = Annotated[Principal, Depends(get_principal_pending_password)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


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
