from collections.abc import Iterable
from datetime import datetime


def merge_busy(
    intervals: Iterable[tuple[datetime, datetime]], start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Touching intervals are glued too, so a reader can't count someone's separate events."""
    pieces = [(max(low, start), min(high, end)) for low, high in intervals]
    merged: list[tuple[datetime, datetime]] = []
    for low, high in sorted(piece for piece in pieces if piece[0] < piece[1]):
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], high))
        else:
            merged.append((low, high))
    return merged
