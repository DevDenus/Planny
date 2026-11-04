import hashlib
import secrets


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 is enough: the token is random, so there is nothing to guess offline."""
    return hashlib.sha256(token.encode()).hexdigest()
