from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling the API. Services take it first, so rights are checked the same way."""

    user_id: UUID
    session_id: UUID
    must_change_password: bool
    kind: Literal["session"] = "session"
    # None means every right of the user. API keys narrow this at stage 6.
    scopes: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class Operator:
    """A person running the CLI on the server. It has no user and no network route."""

    actor: str
