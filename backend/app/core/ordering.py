from collections.abc import Sequence
from uuid import UUID

from fractional_indexing import (  # type: ignore[import-untyped]
    generate_key_between,
    generate_n_keys_between,
)


def key_between(before: str | None, after: str | None) -> str:
    """Moving one row rewrites one key. Keys sort correctly only under COLLATE "C"."""
    return str(generate_key_between(before, after))


def keys_after(last: str | None, count: int) -> list[str]:
    return [str(key) for key in generate_n_keys_between(last, None, count)]


def gap_after_row(
    rows: Sequence[tuple[UUID, str]], after_id: UUID | None
) -> tuple[str | None, str | None]:
    """The rules of `after_id` in one place, for rows sorted by key without the one being placed:
    null is the top, and a row that is gone sends the moved one to the end."""
    if after_id is None:
        return None, rows[0][1] if rows else None
    for index, (row_id, position) in enumerate(rows):
        if row_id == after_id:
            return position, rows[index + 1][1] if index + 1 < len(rows) else None
    return rows[-1][1] if rows else None, None


def key_after_row(rows: Sequence[tuple[UUID, str]], after_id: UUID | None) -> str:
    return key_between(*gap_after_row(rows, after_id))
