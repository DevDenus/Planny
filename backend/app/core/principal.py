from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from uuid import UUID


class Scope(StrEnum):
    events_read = "events:read"
    events_write = "events:write"
    availability_read = "availability:read"
    tasks_read = "tasks:read"
    tasks_write = "tasks:write"
    notifications_read = "notifications:read"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling the API. Services take it first, so rights are checked the same way."""

    user_id: UUID
    # The session or the API key behind the call, depending on kind.
    credential_id: UUID
    must_change_password: bool
    kind: Literal["session", "api_key"] = "session"
    # None means every right of the user. An API key holds only what it was issued with.
    scopes: frozenset[str] | None = None

    def allows(self, *scopes: Scope) -> bool:
        return self.scopes is None or self.scopes.issuperset(scopes)


@dataclass(frozen=True, slots=True)
class Operator:
    """A person running the CLI on the server. It has no user and no network route."""

    actor: str
