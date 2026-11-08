from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

import httpx
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app import proxy
from app.config import Settings
from app.cookies import OpenedSession, SessionCookies
from app.errors import error_response
from app.logs import configure_logging, request_id_var
from app.middleware import RequestContextMiddleware
from app.ratelimit import LoginRateLimiter

PROXIED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


class SpaFiles(StaticFiles):
    """Client-side routes fall back to index.html. Missing hashed assets stay a real 404,
    otherwise a stale tab would get HTML instead of a script."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != HTTPStatus.NOT_FOUND or path.startswith("assets/"):
                raise
            return await super().get_response("index.html", scope)


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_forwarded_for:
        # The rightmost entry is the one Caddy wrote itself, the rest came from the client.
        forwarded = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "127.0.0.1"


def unauthorized(cookies: SessionCookies) -> Response:
    response = error_response(HTTPStatus.UNAUTHORIZED, "unauthorized", "Требуется вход")
    cookies.clear(response)
    return response


def csrf_failed() -> Response:
    return error_response(HTTPStatus.FORBIDDEN, "csrf_failed", "Обновите страницу и повторите")


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    cookies = SessionCookies(settings)
    limiter = LoginRateLimiter(settings.login_rate_limit, settings.login_rate_window_seconds)
    shared_secret = settings.bff_shared_secret.get_secret_value()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=settings.api_url, timeout=proxy.DEFAULT_TIMEOUT, transport=transport
        ) as client:
            app.state.api = client
            yield

    def api(request: Request) -> httpx.AsyncClient:
        client: httpx.AsyncClient = request.app.state.api
        return client

    async def login(request: Request) -> Response:
        # JSON can't be sent cross-origin without a preflight, which is never answered.
        # That is what protects this route: no session exists yet to tie a CSRF token to.
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            return error_response(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", "Нужен JSON"
            )

        ip = client_ip(request, settings)
        retry_after = limiter.hit(ip)
        if retry_after is not None:
            return error_response(
                HTTPStatus.TOO_MANY_REQUESTS,
                "rate_limited",
                "Слишком много попыток входа",
                {"retry_after": retry_after},
            )

        try:
            body = await proxy.read_body(request)
            headers = {
                "content-type": "application/json",
                "x-bff-secret": shared_secret,
                "x-client-ip": ip,
                "x-request-id": request_id_var.get(),
            }
            if user_agent := request.headers.get("user-agent"):
                headers["user-agent"] = user_agent
            upstream = await api(request).post("/api/v1/auth/login", content=body, headers=headers)
        except proxy.BodyTooLarge:
            return too_large()
        except httpx.TransportError:
            return proxy.unavailable()

        if upstream.status_code != HTTPStatus.OK:
            return proxy.relay_response(upstream)

        data = upstream.json()
        response = JSONResponse({"user": data["user"]})
        cookies.issue(response, data["token"])
        return response

    async def logout(request: Request) -> Response:
        session = cookies.open(request)
        if session is None:
            response = Response(status_code=HTTPStatus.NO_CONTENT)
            cookies.clear(response)
            return response
        if not cookies.csrf_matches(request, session.token):
            return csrf_failed()
        try:
            upstream = await api(request).post(
                "/api/v1/auth/logout",
                headers={
                    "authorization": f"Bearer {session.token}",
                    "x-request-id": request_id_var.get(),
                },
            )
        except httpx.TransportError:
            # The cookie stays: dropping it would leave the server session open and unreachable.
            return proxy.unavailable()
        if upstream.is_server_error:
            return proxy.unavailable()
        response = Response(status_code=HTTPStatus.NO_CONTENT)
        cookies.clear(response)
        return response

    async def forward(request: Request, session: OpenedSession, path: str) -> Response:
        try:
            body = await proxy.read_body(request, proxy.body_limit(path))
            upstream = await api(request).request(
                request.method,
                proxy.upstream_url(path, request),
                content=body,
                headers=proxy.upstream_headers(request, session.token),
                timeout=proxy.upstream_timeout(path),
            )
        except proxy.BodyTooLarge:
            return too_large()
        except httpx.TransportError:
            return proxy.unavailable()

        if upstream.status_code == HTTPStatus.UNAUTHORIZED:
            return unauthorized(cookies)
        response = proxy.relay_response(upstream)
        cookies.refresh_if_old(response, session)
        return response

    async def api_proxy(request: Request) -> Response:
        path = request.path_params["path"]
        if not proxy.is_allowed_path(path):
            return error_response(HTTPStatus.NOT_FOUND, "not_found", "Объект не найден")
        session = cookies.open(request)
        if session is None:
            return unauthorized(cookies)
        if request.method not in proxy.SAFE_METHODS and not cookies.csrf_matches(
            request, session.token
        ):
            return csrf_failed()
        return await forward(request, session, path)

    async def bff_not_found(_: Request) -> Response:
        return error_response(HTTPStatus.NOT_FOUND, "not_found", "Объект не найден")

    return Starlette(
        routes=[
            Route("/bff/login", login, methods=["POST"]),
            Route("/bff/logout", logout, methods=["POST"]),
            Route("/bff/api/v1/{path:path}", api_proxy, methods=PROXIED_METHODS),
            Route("/bff/{rest:path}", bff_not_found, methods=PROXIED_METHODS),
            Mount("/", app=SpaFiles(directory=settings.static_dir, check_dir=False)),
        ],
        middleware=[Middleware(RequestContextMiddleware)],
        lifespan=lifespan,
    )


def too_large() -> Response:
    return error_response(
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large", "Слишком большой запрос"
    )
