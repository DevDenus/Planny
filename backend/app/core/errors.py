from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from app.core.logging import request_id_var

# Client-side validation covers the normal path, so these only need to be understandable.
VALIDATION_MESSAGES = {
    "missing": "Обязательное поле",
    "string_too_short": "Слишком короткое значение",
    "string_too_long": "Слишком длинное значение",
}
DEFAULT_VALIDATION_MESSAGE = "Неверное значение"


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def unauthorized(message: str = "Требуется вход") -> AppError:
    return AppError(HTTPStatus.UNAUTHORIZED, "unauthorized", message)


def password_change_required() -> AppError:
    return AppError(
        HTTPStatus.FORBIDDEN,
        "password_change_required",
        "Нужно сменить одноразовый пароль",
    )


def not_found(message: str = "Объект не найден") -> AppError:
    return AppError(HTTPStatus.NOT_FOUND, "not_found", message)


def forbidden(message: str = "Недостаточно прав") -> AppError:
    return AppError(HTTPStatus.FORBIDDEN, "forbidden", message)


def version_conflict(current: dict[str, Any], **extra: Any) -> AppError:
    return AppError(
        HTTPStatus.CONFLICT, "version_conflict", "Объект изменился", {"current": current, **extra}
    )


def id_conflict() -> AppError:
    return AppError(HTTPStatus.CONFLICT, "id_conflict", "Идентификатор уже занят")


def invariant_violation(message: str) -> AppError:
    return AppError(HTTPStatus.CONFLICT, "invariant_violation", message)


def range_too_large() -> AppError:
    return AppError(HTTPStatus.UNPROCESSABLE_ENTITY, "range_too_large", "Период длиннее 366 дней")


def rate_limited(retry_after: int) -> AppError:
    return AppError(
        HTTPStatus.TOO_MANY_REQUESTS,
        "rate_limited",
        "Слишком много попыток входа",
        {"retry_after": retry_after},
    )


def field_error(field: str, message: str) -> AppError:
    return AppError(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "validation_error",
        "Ошибка в данных",
        {"fields": {field: message}},
    )


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get() or "",
        }
    }


def _field_name(location: tuple[int | str, ...]) -> str:
    """Only the leading part names the request body: a comment has a field called `body`."""
    parts = location[1:] if location[:1] == ("body",) else location
    return ".".join(str(part) for part in parts)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # The rejected input is left out on purpose: it may be a password.
        fields = {
            _field_name(error["loc"]): VALIDATION_MESSAGES.get(
                error["type"], DEFAULT_VALIDATION_MESSAGE
            )
            for error in exc.errors()
        }
        return JSONResponse(
            error_body("validation_error", "Ошибка в данных", {"fields": fields}),
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(HTTPException)
    async def handle_http(_: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == HTTPStatus.NOT_FOUND:
            return JSONResponse(error_body("not_found", "Объект не найден"), exc.status_code)
        phrase = HTTPStatus(exc.status_code).phrase
        return JSONResponse(error_body("http_error", phrase), exc.status_code)
