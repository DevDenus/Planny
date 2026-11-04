from typing import Any

from starlette.responses import JSONResponse

from app.logs import request_id_var


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    """Same shape as backend errors, so the SPA has one way to read them."""
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id_var.get(),
            }
        },
        status,
    )
