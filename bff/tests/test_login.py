from pathlib import Path

import httpx
import httpx2
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from app.ratelimit import LoginRateLimiter
from tests.conftest import (
    SESSION_TOKEN,
    SHARED_SECRET,
    FakeApi,
    make_client,
    settings_for,
    sign_in,
)

CREDENTIALS = {"login": "sasha", "password": "secret-password"}


def set_cookie_headers(response: httpx2.Response) -> dict[str, str]:
    headers = response.headers.get_list("set-cookie")
    return {header.split("=", 1)[0]: header for header in headers}


def test_login_sets_protected_cookies_and_hides_the_token(client: TestClient) -> None:
    response = client.post("/bff/login", json=CREDENTIALS)

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": "1", "display_name": "Саша", "color": "teal", "login": "sasha"}
    }
    assert SESSION_TOKEN not in response.text

    cookies = set_cookie_headers(response)
    session = cookies["__Host-planny_session"]
    assert SESSION_TOKEN not in session
    for flag in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"):
        assert flag in session
    assert "Domain" not in session

    csrf = cookies["__Host-planny_csrf"]
    assert "HttpOnly" not in csrf
    for flag in ("Secure", "SameSite=strict", "Path=/"):
        assert flag in csrf


def test_dev_cookies_have_no_host_prefix_and_no_secure(static_dir: Path, fake_api: FakeApi) -> None:
    with make_client(settings_for(static_dir, cookie_secure=False), fake_api) as client:
        response = client.post("/bff/login", json=CREDENTIALS)

    cookies = set_cookie_headers(response)
    assert set(cookies) == {"planny_session", "planny_csrf"}
    assert "Secure" not in cookies["planny_session"]
    assert "HttpOnly" in cookies["planny_session"]


def test_login_passes_secret_ip_and_request_id(client: TestClient, fake_api: FakeApi) -> None:
    response = client.post(
        "/bff/login",
        json=CREDENTIALS,
        headers={"User-Agent": "Firefox", "X-Client-IP": "6.6.6.6", "X-BFF-Secret": "forged"},
    )

    sent = fake_api.last
    assert sent.headers["x-bff-secret"] == SHARED_SECRET
    assert sent.headers["x-client-ip"] == "203.0.113.5"
    assert sent.headers["user-agent"] == "Firefox"
    assert sent.headers["x-request-id"] == response.headers["x-request-id"]


def test_forwarded_ip_is_ignored_unless_configured(client: TestClient, fake_api: FakeApi) -> None:
    client.post("/bff/login", json=CREDENTIALS, headers={"X-Forwarded-For": "6.6.6.6"})
    assert fake_api.last.headers["x-client-ip"] == "203.0.113.5"


def test_behind_caddy_the_rightmost_forwarded_ip_is_used(
    static_dir: Path, fake_api: FakeApi
) -> None:
    settings = settings_for(static_dir, trust_forwarded_for=True)
    with make_client(settings, fake_api) as client:
        client.post(
            "/bff/login",
            json=CREDENTIALS,
            headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.7"},
        )
    assert fake_api.last.headers["x-client-ip"] == "198.51.100.7"


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded"])
def test_login_refuses_what_a_foreign_form_can_send(
    client: TestClient, fake_api: FakeApi, content_type: str
) -> None:
    response = client.post(
        "/bff/login", content='{"login":"x"}', headers={"Content-Type": content_type}
    )
    assert response.status_code == 415
    assert fake_api.requests == []


def test_login_errors_pass_through_without_cookies(client: TestClient, fake_api: FakeApi) -> None:
    body = {"error": {"code": "unauthorized", "message": "Неверный логин или пароль"}}
    fake_api.handler = lambda _: httpx.Response(401, json=body)

    response = client.post("/bff/login", json=CREDENTIALS)

    assert response.status_code == 401
    assert response.json() == body
    assert "set-cookie" not in response.headers


def test_login_limit_per_ip_stops_before_the_backend(static_dir: Path, fake_api: FakeApi) -> None:
    settings = settings_for(static_dir, login_rate_limit=2)
    with make_client(settings, fake_api) as client:
        assert client.post("/bff/login", json=CREDENTIALS).status_code == 200
        assert client.post("/bff/login", json=CREDENTIALS).status_code == 200
        limited = client.post("/bff/login", json=CREDENTIALS)

    assert limited.status_code == 429
    error = limited.json()["error"]
    assert error["code"] == "rate_limited"
    assert 0 < error["details"]["retry_after"] <= 300
    assert len(fake_api.requests) == 2


def test_rate_limiter_window_slides_and_forgets_idle_addresses() -> None:
    now = [0.0]
    limiter = LoginRateLimiter(2, 10, clock=lambda: now[0])

    assert limiter.hit("a") is None
    now[0] = 6
    assert limiter.hit("a") is None
    assert limiter.hit("a") == 4
    assert limiter.hit("b") is None

    now[0] = 10.5
    assert limiter.hit("a") is None

    now[0] = 100
    limiter.hit("c")
    assert set(limiter._hits) == {"c"}


def test_backend_down_during_login_is_a_clean_error(client: TestClient, fake_api: FakeApi) -> None:
    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fake_api.handler = refuse
    response = client.post("/bff/login", json=CREDENTIALS)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_logout_requires_csrf(client: TestClient, fake_api: FakeApi) -> None:
    sign_in(client)
    response = client.post("/bff/logout")
    assert response.status_code == 403
    assert fake_api.last.url.path == "/api/v1/auth/login"


def test_logout_closes_the_session_and_clears_cookies(
    client: TestClient, fake_api: FakeApi
) -> None:
    csrf = sign_in(client)
    response = client.post("/bff/logout", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 204
    assert fake_api.last.url.path == "/api/v1/auth/logout"
    assert fake_api.last.headers["authorization"] == f"Bearer {SESSION_TOKEN}"
    cookies = set_cookie_headers(response)
    assert set(cookies) == {"__Host-planny_session", "__Host-planny_csrf"}
    assert all("Max-Age=0" in header for header in cookies.values())


def test_logout_keeps_the_cookie_if_the_server_could_not_close_the_session(
    client: TestClient, fake_api: FakeApi
) -> None:
    csrf = sign_in(client)

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fake_api.handler = refuse
    response = client.post("/bff/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 502
    assert "set-cookie" not in response.headers


def test_logout_without_a_session_just_clears_cookies(
    client: TestClient, fake_api: FakeApi
) -> None:
    response = client.post("/bff/logout")
    assert response.status_code == 204
    assert fake_api.requests == []


def test_a_cookie_sealed_with_another_key_does_not_open(
    client: TestClient, fake_api: FakeApi
) -> None:
    forged = Fernet(Fernet.generate_key()).encrypt(b"stolen").decode()
    client.cookies.set("__Host-planny_session", forged)
    assert client.get("/bff/api/v1/me").status_code == 401
    assert fake_api.requests == []
