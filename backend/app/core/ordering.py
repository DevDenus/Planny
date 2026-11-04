from fractional_indexing import generate_key_between  # type: ignore[import-untyped]


def key_between(before: str | None, after: str | None) -> str:
    """Moving one row rewrites one key. Keys sort correctly only under COLLATE "C"."""
    return str(generate_key_between(before, after))
