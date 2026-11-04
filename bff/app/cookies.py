import hashlib
import hmac
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings

# The server side slides on use, a browser cookie has a fixed lifetime. Re-issuing it once
# a day keeps an active user signed in past the first 30 days.
REFRESH_AFTER_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class OpenedSession:
    token: str
    age_seconds: int


class SessionCookies:
    """The session token lives only encrypted in the browser, so the BFF stays stateless.

    The CSRF token is an HMAC of the session token. It needs no storage, survives a restart
    and is readable by the SPA from a separate cookie without exposing the session.
    """

    def __init__(self, settings: Settings) -> None:
        key = settings.cookie_key.get_secret_value().encode()
        self._fernet = Fernet(key)
        self._csrf_key = hmac.new(key, b"planny-csrf", hashlib.sha256).digest()
        self._secure = settings.cookie_secure
        self._max_age = settings.session_ttl_days * 24 * 60 * 60
        prefix = "__Host-" if settings.cookie_secure else ""
        self.session_name = f"{prefix}planny_session"
        self.csrf_name = f"{prefix}planny_csrf"

    def open(self, request: Request) -> OpenedSession | None:
        sealed = request.cookies.get(self.session_name)
        if sealed is None:
            return None
        try:
            token = self._fernet.decrypt(sealed.encode(), ttl=self._max_age)
            issued_at = self._fernet.extract_timestamp(sealed.encode())
        except InvalidToken:
            return None
        return OpenedSession(token=token.decode(), age_seconds=int(time.time()) - issued_at)

    def csrf_token(self, session_token: str) -> str:
        return hmac.new(self._csrf_key, session_token.encode(), hashlib.sha256).hexdigest()

    def csrf_matches(self, request: Request, session_token: str) -> bool:
        supplied = request.headers.get("x-csrf-token", "")
        return hmac.compare_digest(supplied.encode(), self.csrf_token(session_token).encode())

    def issue(self, response: Response, session_token: str) -> None:
        response.set_cookie(
            self.session_name,
            self._fernet.encrypt(session_token.encode()).decode(),
            max_age=self._max_age,
            path="/",
            secure=self._secure,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            self.csrf_name,
            self.csrf_token(session_token),
            max_age=self._max_age,
            path="/",
            secure=self._secure,
            httponly=False,
            samesite="strict",
        )

    def refresh_if_old(self, response: Response, session: OpenedSession) -> None:
        if session.age_seconds >= REFRESH_AFTER_SECONDS:
            self.issue(response, session.token)

    def clear(self, response: Response) -> None:
        for name, httponly in ((self.session_name, True), (self.csrf_name, False)):
            response.delete_cookie(
                name, path="/", secure=self._secure, httponly=httponly, samesite="strict"
            )
