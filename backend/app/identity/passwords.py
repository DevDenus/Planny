import asyncio
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


@lru_cache
def _decoy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    # Argon2id takes tens of milliseconds and would stall the event loop.
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Spends the same time when there is no such user, so logins can't be probed by timing."""
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash or _decoy_hash(), password)
    except VerificationError, InvalidHashError:
        return False


def generate_one_time_password() -> str:
    return secrets.token_urlsafe(12)
