from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import field_error, range_too_large

MAX_PERIOD = timedelta(days=366)
# Arithmetic around a period has to stay inside the years a date can hold.
EARLIEST = datetime(3, 1, 1, tzinfo=UTC)
LATEST = datetime(9997, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Period:
    """A half-open period of time and the calendar days it touches in the zone of the reader.
    Moments compare with the first pair, dates without time with the second."""

    start: datetime
    end: datetime
    first_day: date
    last_day: date


def period_of(start: datetime, end: datetime, timezone: ZoneInfo) -> Period:
    if end <= start:
        raise field_error("to", "Конец периода должен быть позже начала")
    if end - start > MAX_PERIOD:
        raise range_too_large()
    if start < EARLIEST or end > LATEST:
        raise field_error("from", "Такой период не поддерживается")
    return Period(
        start=start,
        end=end,
        first_day=start.astimezone(timezone).date(),
        # The end is not in the period, so midnight belongs to the day before it.
        last_day=(end - timedelta(microseconds=1)).astimezone(timezone).date(),
    )
