import time

import httpx
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from app.cookies import REFRESH_AFTER_SECONDS
from app.proxy import is_allowed_path
from tests.conftest import COOKIE_KEY, SESSION_TOKEN, FakeApi, sign_in

SESSION_COOKIE = "__Host-planny_session"


def seal_at(seconds_ago: int) -> str:
    moment = int(time.time()) - seconds_ago
    return Fernet(COOKIE_KEY).encrypt_at_time(SESSION_TOKEN.encode(), moment).decode()


def test_proxy_adds_the_token_and_passes_the_request_through(
    client: TestClient, fake_api: FakeApi
) -> None:
    csrf = sign_in(client)
    response = client.patch(
        "/bff/api/v1/tasks/7?status=open&sort=due",
        json={"title": "Купить хлеб"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    sent = fake_api.last
    assert sent.method == "PATCH"
    assert str(sent.url) == "http://api.test/api/v1/tasks/7?status=open&sort=due"
    assert b"\xd0\x9a" in sent.content
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["authorization"] == f"Bearer {SESSION_TOKEN}"
    assert sent.headers["x-request-id"] == response.headers["x-request-id"]


def test_proxy_drops_what_the_browser_could_use_to_pose_as_the_bff(
    client: TestClient, fake_api: FakeApi
) -> None:
    sign_in(client)
    client.get(
        "/bff/api/v1/me",
        headers={
            "Authorization": "Bearer forged",
            "X-BFF-Secret": "forged",
            "X-Client-IP": "6.6.6.6",
            "X-Request-ID": "forged",
            "X-Forwarded-For": "6.6.6.6",
        },
    )

    sent = fake_api.last
    assert sent.headers["authorization"] == f"Bearer {SESSION_TOKEN}"
    assert sent.headers["x-request-id"] != "forged"
    for name in ("cookie", "x-bff-secret", "x-client-ip", "x-forwarded-for", "x-csrf-token"):
        assert name not in sent.headers


@pytest.mark.parametrize(
    "path",
    [
        "auth/login",
        "auth/logout",
        "auth",
        "auth/change-password/x",
        "health",
        "admin",
        "openapi.json",
        "me/%2e%2e/auth/login",
        "me%2F..%2Fauth%2Flogin",
        "me//x",
        "/me",
    ],
)
def test_routes_outside_the_allowlist_never_reach_the_backend(
    client: TestClient, fake_api: FakeApi, path: str
) -> None:
    sign_in(client)
    calls = len(fake_api.requests)
    response = client.get(f"/bff/api/v1/{path}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert len(fake_api.requests) == calls


@pytest.mark.parametrize(
    "path", ["me/../auth/login", "me/./x", "./me", "..", "me/..", "auth/change-password/.."]
)
def test_dot_segments_are_refused(path: str) -> None:
    """Checked directly: HTTP clients collapse literal dots before the request is sent."""
    assert not is_allowed_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "me",
        "users",
        "sync",
        "boards/1/columns",
        "calendar/items",
        "notifications/read-all",
        "assistant/status",
        "assistant/chats/1/messages",
    ],
)
def test_allowed_prefixes_are_proxied(client: TestClient, fake_api: FakeApi, path: str) -> None:
    sign_in(client)
    assert client.get(f"/bff/api/v1/{path}").status_code == 200
    assert fake_api.last.url.path == f"/api/v1/{path}"


def test_change_password_is_reachable(client: TestClient, fake_api: FakeApi) -> None:
    csrf = sign_in(client)
    response = client.post(
        "/bff/api/v1/auth/change-password",
        json={"new_password": "x"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert fake_api.last.url.path == "/api/v1/auth/change-password"


def test_no_session_is_401_and_reaches_nothing(client: TestClient, fake_api: FakeApi) -> None:
    response = client.get("/bff/api/v1/me")
    assert response.status_code == 401
    assert fake_api.requests == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_changing_methods_need_the_csrf_token(
    client: TestClient, fake_api: FakeApi, method: str
) -> None:
    sign_in(client)
    calls = len(fake_api.requests)
    for headers in ({}, {"X-CSRF-Token": "wrong"}):
        response = client.request(method, "/bff/api/v1/tasks/1", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"
    assert len(fake_api.requests) == calls


def test_reading_needs_no_csrf_token(client: TestClient) -> None:
    sign_in(client)
    assert client.get("/bff/api/v1/me").status_code == 200


def test_a_session_ended_on_the_server_clears_the_browser_cookies(
    client: TestClient, fake_api: FakeApi
) -> None:
    sign_in(client)
    fake_api.handler = lambda _: httpx.Response(401, json={"error": {}})

    response = client.get("/bff/api/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert any("Max-Age=0" in h for h in response.headers.get_list("set-cookie"))


def test_backend_errors_pass_through_unchanged(client: TestClient, fake_api: FakeApi) -> None:
    sign_in(client)
    body = {"error": {"code": "password_change_required", "message": "Нужно сменить пароль"}}
    fake_api.handler = lambda _: httpx.Response(403, json=body)

    response = client.get("/bff/api/v1/users")

    assert response.status_code == 403
    assert response.json() == body


def test_cookies_from_the_backend_never_reach_the_browser(
    client: TestClient, fake_api: FakeApi
) -> None:
    sign_in(client)
    fake_api.handler = lambda _: httpx.Response(
        200, json={}, headers={"set-cookie": "leaked=1", "server": "uvicorn"}
    )
    response = client.get("/bff/api/v1/me")
    assert "leaked" not in response.headers.get("set-cookie", "")
    assert response.headers.get("server") != "uvicorn"


def test_backend_down_is_a_clean_error(client: TestClient, fake_api: FakeApi) -> None:
    sign_in(client)

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fake_api.handler = refuse
    response = client.get("/bff/api/v1/me")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_oversized_body_is_refused(client: TestClient, fake_api: FakeApi) -> None:
    csrf = sign_in(client)
    calls = len(fake_api.requests)
    response = client.post(
        "/bff/api/v1/tasks",
        content=b"x" * (1024 * 1024 + 1),
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 413
    assert len(fake_api.requests) == calls


def test_a_recording_may_be_larger_than_other_bodies(client: TestClient, fake_api: FakeApi) -> None:
    csrf = sign_in(client)
    headers = {"X-CSRF-Token": csrf, "Content-Type": "audio/webm"}

    allowed = client.post(
        "/bff/api/v1/assistant/transcribe", content=b"x" * (2 * 1024 * 1024), headers=headers
    )
    assert allowed.status_code == 200
    assert len(fake_api.last.content) == 2 * 1024 * 1024
    assert fake_api.last.headers["content-type"] == "audio/webm"

    calls = len(fake_api.requests)
    refused = client.post(
        "/bff/api/v1/assistant/transcribe", content=b"x" * (9 * 1024 * 1024), headers=headers
    )
    assert refused.status_code == 413
    assert len(fake_api.requests) == calls


def test_the_larger_limit_is_for_recordings_only(client: TestClient, fake_api: FakeApi) -> None:
    csrf = sign_in(client)
    calls = len(fake_api.requests)
    for path in ("tasks", "assistant/chats"):
        response = client.post(
            f"/bff/api/v1/{path}", content=b"x" * (2 * 1024 * 1024), headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 413
    assert len(fake_api.requests) == calls


def test_the_assistant_gets_longer_to_answer(client: TestClient, fake_api: FakeApi) -> None:
    sign_in(client)

    client.get("/bff/api/v1/assistant/status")
    assistant = fake_api.last.extensions["timeout"]
    client.get("/bff/api/v1/me")
    other = fake_api.last.extensions["timeout"]

    assert assistant["read"] == 90
    assert other["read"] == 30


def test_a_day_old_cookie_is_reissued_for_an_active_user(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE, seal_at(REFRESH_AFTER_SECONDS + 1))
    response = client.get("/bff/api/v1/me")
    assert response.status_code == 200
    assert SESSION_COOKIE in response.headers["set-cookie"]


def test_a_fresh_cookie_is_not_reissued(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE, seal_at(60))
    response = client.get("/bff/api/v1/me")
    assert "set-cookie" not in response.headers


def test_a_cookie_past_its_lifetime_does_not_open(client: TestClient, fake_api: FakeApi) -> None:
    client.cookies.set(SESSION_COOKIE, seal_at(31 * 24 * 60 * 60))
    assert client.get("/bff/api/v1/me").status_code == 401
    assert fake_api.requests == []


def test_client_routes_get_the_spa(client: TestClient) -> None:
    for path in ("/", "/calendar", "/boards/42", "/login"):
        response = client.get(path)
        assert response.status_code == 200
        assert "<title>Planny</title>" in response.text
        assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_for_good(client: TestClient) -> None:
    response = client.get("/assets/app-abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_a_missing_asset_is_a_real_404(client: TestClient) -> None:
    assert client.get("/assets/old-chunk.js").status_code == 404


def test_files_outside_the_static_directory_are_unreachable(client: TestClient) -> None:
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        assert "secret" not in client.get(path).text


def test_unknown_bff_routes_are_404_not_the_spa(client: TestClient) -> None:
    response = client.get("/bff/whatever")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_every_response_carries_the_security_headers(client: TestClient) -> None:
    for path in ("/", "/bff/whatever"):
        headers = client.get(path).headers
        assert "default-src 'self'" in headers["content-security-policy"]
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
