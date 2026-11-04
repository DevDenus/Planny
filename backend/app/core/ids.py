from uuid import UUID, uuid7


def new_id() -> UUID:
    """Time-ordered UUID, so primary key indexes stay compact."""
    return uuid7()
