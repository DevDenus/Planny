from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator

PASSWORD_MIN_LENGTH = 8
# Argon2id accepts any length, the cap only limits how much work one request can ask for.
PASSWORD_MAX_LENGTH = 1024

AvatarColor = Literal["violet", "blue", "teal", "green", "yellow", "orange", "red", "pink"]
Password = Annotated[str, Field(max_length=PASSWORD_MAX_LENGTH)]


@lru_cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: Password = Field(min_length=1)


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    color: str


class CurrentUser(UserSummary):
    login: str
    timezone: str
    must_change_password: bool


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user: CurrentUser


class ChangePasswordRequest(BaseModel):
    current_password: Password | None = None
    new_password: Password = Field(min_length=PASSWORD_MIN_LENGTH)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = None
    color: AvatarColor | None = None

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in _timezones():
            raise ValueError("unknown timezone")
        return value


class UserList(BaseModel):
    items: list[UserSummary]


class Health(BaseModel):
    status: Literal["ok"]
