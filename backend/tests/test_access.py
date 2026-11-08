"""AC-02 in its authorization part and AC-03: what the network can and cannot reach."""

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import bearer, login_as, make_user

PUBLIC = {("GET", "/api/v1/health")}
BFF_ONLY = {("POST", "/api/v1/auth/login")}
EXPECTED_ROUTES = {
    ("GET", "/api/v1/health"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/change-password"),
    ("GET", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
    ("GET", "/api/v1/users"),
    ("GET", "/api/v1/boards"),
    ("POST", "/api/v1/boards"),
    ("GET", "/api/v1/boards/{board_id}"),
    ("PATCH", "/api/v1/boards/{board_id}"),
    ("GET", "/api/v1/boards/{board_id}/columns"),
    ("POST", "/api/v1/boards/{board_id}/columns"),
    ("PATCH", "/api/v1/boards/{board_id}/columns/{column_id}"),
    ("DELETE", "/api/v1/boards/{board_id}/columns/{column_id}"),
    ("POST", "/api/v1/boards/{board_id}/columns/{column_id}/move"),
    ("GET", "/api/v1/boards/{board_id}/labels"),
    ("POST", "/api/v1/boards/{board_id}/labels"),
    ("PATCH", "/api/v1/boards/{board_id}/labels/{label_id}"),
    ("DELETE", "/api/v1/boards/{board_id}/labels/{label_id}"),
    ("GET", "/api/v1/boards/{board_id}/members"),
    ("POST", "/api/v1/boards/{board_id}/members"),
    ("PATCH", "/api/v1/boards/{board_id}/members/{user_id}"),
    ("DELETE", "/api/v1/boards/{board_id}/members/{user_id}"),
    ("GET", "/api/v1/tasks"),
    ("POST", "/api/v1/tasks"),
    ("GET", "/api/v1/tasks/{task_id}"),
    ("PATCH", "/api/v1/tasks/{task_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}"),
    ("POST", "/api/v1/tasks/{task_id}/move"),
    ("POST", "/api/v1/tasks/{task_id}/complete"),
    ("POST", "/api/v1/tasks/{task_id}/reopen"),
    ("POST", "/api/v1/tasks/{task_id}/checklist"),
    ("PATCH", "/api/v1/tasks/{task_id}/checklist/{item_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}/checklist/{item_id}"),
    ("GET", "/api/v1/tasks/{task_id}/comments"),
    ("POST", "/api/v1/tasks/{task_id}/comments"),
    ("PATCH", "/api/v1/tasks/{task_id}/comments/{comment_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}/comments/{comment_id}"),
    ("GET", "/api/v1/tasks/{task_id}/activity"),
    ("POST", "/api/v1/tasks/{task_id}/event-links"),
    ("DELETE", "/api/v1/tasks/{task_id}/event-links/{event_id}"),
    ("GET", "/api/v1/calendar/items"),
    ("GET", "/api/v1/events"),
    ("POST", "/api/v1/events"),
    ("GET", "/api/v1/events/{event_id}"),
    ("PATCH", "/api/v1/events/{event_id}"),
    ("DELETE", "/api/v1/events/{event_id}"),
    ("DELETE", "/api/v1/events/{event_id}/participants/me"),
    ("GET", "/api/v1/availability"),
    ("GET", "/api/v1/search"),
    ("GET", "/api/v1/categories"),
    ("POST", "/api/v1/categories"),
    ("PATCH", "/api/v1/categories/{category_id}"),
    ("DELETE", "/api/v1/categories/{category_id}"),
    ("GET", "/api/v1/notifications"),
    ("POST", "/api/v1/notifications/read-all"),
    ("POST", "/api/v1/notifications/{notification_id}/read"),
    ("GET", "/api/v1/sync"),
    ("GET", "/api/v1/assistant/status"),
    ("POST", "/api/v1/assistant/transcribe"),
    ("GET", "/api/v1/assistant/chats"),
    ("POST", "/api/v1/assistant/chats"),
    ("GET", "/api/v1/assistant/chats/{chat_id}"),
    ("DELETE", "/api/v1/assistant/chats/{chat_id}"),
    ("POST", "/api/v1/assistant/chats/{chat_id}/messages"),
}


def routes(app: FastAPI) -> set[tuple[str, str]]:
    """Read from the schema because app.routes keeps included routers unexpanded."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }


def test_network_surface_is_exactly_the_documented_one(app: FastAPI) -> None:
    """No registration or admin route may appear without changing this list on purpose."""
    assert routes(app) == EXPECTED_ROUTES


def test_api_schema_and_docs_are_not_served(app: FastAPI) -> None:
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None


async def test_every_protected_route_rejects_missing_and_invalid_tokens(
    app: FastAPI, client: AsyncClient
) -> None:
    for method, path in routes(app) - PUBLIC - BFF_ONLY:
        url = path.removeprefix("/api/v1/")
        for headers in ({}, bearer("not-a-real-token")):
            response = await client.request(method, url, headers=headers, json={})
            assert response.status_code == 401, (method, path)
            assert response.json()["error"]["code"] == "unauthorized"


async def test_health_needs_no_token(client: AsyncClient) -> None:
    response = await client.get("health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_login_is_closed_without_the_bff_secret(client: AsyncClient) -> None:
    await make_user()
    body = {"login": "sasha", "password": "correct-horse-battery"}
    for headers in (
        {"X-Client-IP": "10.0.0.1"},
        {"X-Client-IP": "10.0.0.1", "X-BFF-Secret": "wrong"},
    ):
        response = await client.post("auth/login", json=body, headers=headers)
        assert response.status_code == 401
        assert "token" not in response.json()


async def test_errors_have_the_common_shape_and_echo_the_request_id(client: AsyncClient) -> None:
    response = await client.get("no-such-route", headers={"X-Request-ID": "req-42"})
    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req-42"
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Объект не найден",
            "details": {},
            "request_id": "req-42",
        }
    }


async def test_request_id_with_unsafe_characters_is_replaced(client: AsyncClient) -> None:
    response = await client.get("health", headers={"X-Request-ID": 'bad"id\tinjection'})
    assert response.headers["x-request-id"] != 'bad"id\tinjection'


async def test_validation_error_does_not_echo_the_password(client: AsyncClient) -> None:
    await make_user()
    token = await login_as(client)
    secret = "short"
    response = await client.post(
        "auth/change-password",
        json={"current_password": "x", "new_password": secret},
        headers=bearer(token),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"] == {
        "new_password": "Слишком короткое значение"
    }
    assert secret not in response.text
