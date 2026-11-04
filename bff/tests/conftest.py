from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from app.config import Settings
from app.main import create_app

SHARED_SECRET = "bff-shared-secret-bff-shared-secret"
COOKIE_KEY = Fernet.generate_key().decode()
SESSION_TOKEN = "opaque-session-token"
USER = {"id": "1", "display_name": "Саша", "color": "teal", "login": "sasha"}

Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeApi:
    """Stands in for the backend and records what the BFF sent to it."""

    requests: list[httpx.Request] = field(default_factory=list)
    handler: Handler | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.handler is not None:
            return self.handler(request)
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(
                200, json={"token": SESSION_TOKEN, "expires_at": "2030-01-01", "user": USER}
            )
        if request.url.path == "/api/v1/auth/logout":
            return httpx.Response(204)
        return httpx.Response(200, json={"ok": True}, headers={"x-request-id": "ignored"})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def fake_api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Planny</title>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log('planny')")
    return tmp_path


def settings_for(static_dir: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "bff_shared_secret": SHARED_SECRET,
        "cookie_key": COOKIE_KEY,
        "api_url": "http://api.test",
        "static_dir": static_dir,
    }
    return Settings(**{**values, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def settings(static_dir: Path) -> Settings:
    return settings_for(static_dir)


def make_client(settings: Settings, fake_api: FakeApi) -> TestClient:
    app = create_app(settings, transport=httpx.MockTransport(fake_api))
    return TestClient(app, base_url="https://planny.test", client=("203.0.113.5", 5000))


@pytest.fixture
def client(settings: Settings, fake_api: FakeApi) -> Iterator[TestClient]:
    with make_client(settings, fake_api) as test_client:
        yield test_client


def sign_in(client: TestClient) -> str:
    """Logs in and returns the CSRF token the SPA would read from its cookie."""
    response = client.post("/bff/login", json={"login": "sasha", "password": "secret-password"})
    assert response.status_code == 200
    csrf: str = client.cookies["__Host-planny_csrf"]
    return csrf
