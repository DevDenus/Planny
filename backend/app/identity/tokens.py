import hashlib
import re
import secrets
from dataclasses import dataclass

API_KEY_RE = re.compile(r"pln_([0-9a-f]{8})_([A-Za-z0-9_-]{43})")


@dataclass(frozen=True, slots=True)
class ApiKeyToken:
    prefix: str
    secret: str

    def __str__(self) -> str:
        return f"pln_{self.prefix}_{self.secret}"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_api_key() -> ApiKeyToken:
    return ApiKeyToken(prefix=secrets.token_hex(4), secret=secrets.token_urlsafe(32))


def parse_api_key(token: str) -> ApiKeyToken | None:
    """The whole shape is matched, so a session token can't be taken for a key by chance."""
    match = API_KEY_RE.fullmatch(token)
    return ApiKeyToken(prefix=match[1], secret=match[2]) if match else None


def hash_token(token: str) -> str:
    """SHA-256 is enough: the token is random, so there is nothing to guess offline."""
    return hashlib.sha256(token.encode()).hexdigest()
