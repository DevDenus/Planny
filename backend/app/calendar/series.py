"""Repeats live as a rule next to the first occurrence and unfold on reading.

A series is counted in the local time of its event. In UTC "the 1st at 01:00 in Moscow" turns
into "the 31st at 22:00", and months without a 31st would lose it. All-day events have no zone
in their dates, so for them the same arithmetic runs on bare dates.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from dateutil.rrule import rrule, rruleset, rrulestr

from app.calendar.models import Event
from app.core.period import Period

Freq = Literal["daily", "weekly", "monthly"]

_RULE = re.compile(r"FREQ=(?P<freq>[A-Z]+)(;UNTIL=(?P<until>\d{8})T235959|;COUNT=(?P<count>\d+))?")
# Other steps are short anyway: twelve a year for months, and COUNT is limited by the API.
_STEP_DAYS = {"daily": 1, "weekly": 7}
# A clock change skips or repeats an hour, so local time can't tell which of two moments is
# earlier there. A rule is walked this much wider, and real moments make the exact choice.
_CLOCK_MARGIN = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Recurrence:
    freq: Freq
    until: date | None = None
    count: int | None = None


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One repeat of an event: moments for an event with a time, dates for an all-day one."""

    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None

    @property
    def start(self) -> datetime | date:
        """Together with the id of the event this names the occurrence."""
        start = self.start_at or self.start_date
        assert start is not None  # noqa: S101  # the constructors below fill one of the two
        return start


def build_rule(recurrence: Recurrence | None) -> str | None:
    """UNTIL stays in local time without Z: dateutil refuses a UTC one with a local start."""
    if recurrence is None:
        return None
    rule = f"FREQ={recurrence.freq.upper()}"
    if recurrence.until is not None:
        return f"{rule};UNTIL={recurrence.until:%Y%m%d}T235959"
    if recurrence.count is not None:
        return f"{rule};COUNT={recurrence.count}"
    return rule


def parse_rule(rule: str | None) -> Recurrence | None:
    """Only the server writes rules, so one that doesn't match is a bug, not bad input."""
    if rule is None:
        return None
    match = _RULE.fullmatch(rule)
    if match is None:
        raise ValueError(f"unknown recurrence rule: {rule}")
    until = match["until"]
    freq: Freq = match["freq"].lower()  # type: ignore[assignment]  # build_rule wrote it
    return Recurrence(
        freq=freq,
        until=datetime.strptime(until, "%Y%m%d").date() if until else None,
        count=int(match["count"]) if match["count"] else None,
    )


def _to_local(moment: datetime, timezone: ZoneInfo) -> datetime:
    return moment.astimezone(timezone).replace(tzinfo=None)


def _to_utc(local: datetime, timezone: ZoneInfo) -> datetime:
    return local.replace(tzinfo=timezone).astimezone(UTC)


def _zone(event: Event) -> ZoneInfo:
    return ZoneInfo(event.timezone)


def _first_local(event: Event) -> datetime:
    if event.all_day:
        assert event.start_date is not None  # noqa: S101  # the time_shape constraint
        return datetime.combine(event.start_date, time.min)
    assert event.start_at is not None  # noqa: S101  # the time_shape constraint
    return _to_local(event.start_at, _zone(event))


def first_day(event: Event) -> date:
    """The local date of the first occurrence: `until` is compared with it."""
    return _first_local(event).date()


def occurrence_length(event: Event) -> timedelta:
    """Every occurrence lasts as long as the first one."""
    if event.all_day:
        assert event.start_date is not None  # noqa: S101  # the time_shape constraint
        assert event.end_date is not None  # noqa: S101  # the time_shape constraint
        return event.end_date - event.start_date
    assert event.start_at is not None  # noqa: S101  # the time_shape constraint
    assert event.end_at is not None  # noqa: S101  # the time_shape constraint
    return event.end_at - event.start_at


def _at(event: Event, local: datetime) -> Occurrence:
    length = occurrence_length(event)
    if event.all_day:
        return Occurrence(start_date=local.date(), end_date=local.date() + length)
    start = _to_utc(local, _zone(event))
    return Occurrence(start_at=start, end_at=start + length)


def _rule(event: Event, near: datetime | None = None) -> rrule | rruleset:
    """A rule walks from its first date. Daily series in a far year would take a million steps,
    so the walk starts from the last whole step before `near`: it has to be no later than the
    occurrence asked for. COUNT needs the whole walk, but it is short."""
    assert event.recurrence_rule is not None  # noqa: S101  # the callers check it
    first = _first_local(event)
    recurrence = parse_rule(event.recurrence_rule)
    assert recurrence is not None  # noqa: S101  # recurrence_rule is set
    step = _STEP_DAYS.get(recurrence.freq)
    if step is not None and recurrence.count is None and near is not None:
        # Past the end of the series the walk has to stop before it, or it finds nothing at all.
        if recurrence.until is not None:
            near = min(near, datetime.combine(recurrence.until, time.max))
        if near > first:
            first += timedelta(days=(near - first).days // step * step)
    return rrulestr(event.recurrence_rule, dtstart=first)


def _touches(occurrence: Occurrence, period: Period) -> bool:
    if occurrence.start_date is not None and occurrence.end_date is not None:
        return occurrence.start_date <= period.last_day and occurrence.end_date >= period.first_day
    assert occurrence.start_at is not None  # noqa: S101  # one of the two pairs is set
    assert occurrence.end_at is not None  # noqa: S101  # one of the two pairs is set
    return occurrence.start_at < period.end and occurrence.end_at > period.start


def occurrences_in(event: Event, period: Period) -> list[Occurrence]:
    if event.recurrence_rule is None:
        single = _at(event, _first_local(event))
        return [single] if _touches(single, period) else []
    length = occurrence_length(event)
    if event.all_day:
        since = datetime.combine(period.first_day - length, time.min)
        until = datetime.combine(period.last_day, time.max)
    else:
        since = _to_local(period.start - length, _zone(event)) - _CLOCK_MARGIN
        until = _to_local(period.end, _zone(event)) + _CLOCK_MARGIN
    found = (_at(event, local) for local in _rule(event, since).between(since, until, inc=True))
    return [occurrence for occurrence in found if _touches(occurrence, period)]


def start_moment(event: Event, occurrence: Occurrence) -> datetime:
    """An all-day occurrence starts at midnight in the zone of the event."""
    if occurrence.start_at is not None:
        return occurrence.start_at
    assert occurrence.start_date is not None  # noqa: S101  # one of the two pairs is set
    return _to_utc(datetime.combine(occurrence.start_date, time.min), _zone(event))


def next_occurrence(event: Event, moment: datetime) -> Occurrence | None:
    """The first occurrence that starts later than the moment."""
    if event.recurrence_rule is None:
        single = _at(event, _first_local(event))
        return single if start_moment(event, single) > moment else None
    local = _to_local(moment, _zone(event)) - _CLOCK_MARGIN
    for found in _rule(event, local).xafter(local):
        occurrence = _at(event, found)
        if start_moment(event, occurrence) > moment:
            return occurrence
    return None


def last_started(event: Event, moment: datetime) -> Occurrence | None:
    """The last occurrence that starts no later than the moment."""
    if event.recurrence_rule is None:
        single = _at(event, _first_local(event))
        return single if start_moment(event, single) <= moment else None
    local = _to_local(moment, _zone(event))
    early, late = local - _CLOCK_MARGIN, local + _CLOCK_MARGIN
    rule = _rule(event, early)
    for found in reversed(rule.between(early, late, inc=True)):
        occurrence = _at(event, found)
        if start_moment(event, occurrence) <= moment:
            return occurrence
    earlier = rule.before(early)
    return None if earlier is None else _at(event, earlier)


def closest_distance(event: Event, moment: datetime) -> timedelta:
    """How far from the moment the closest occurrence is, in either direction."""
    around = (last_started(event, moment), next_occurrence(event, moment))
    return min(abs(start_moment(event, item) - moment) for item in around if item is not None)


def series_end(event: Event) -> datetime | None:
    """The end of the last occurrence, None if there is none. Used to choose by period, where a
    date of an all-day event has no zone, so it counts as the midnight UTC after that day."""
    last = _at(event, _first_local(event))
    if event.recurrence_rule is not None:
        recurrence = parse_rule(event.recurrence_rule)
        assert recurrence is not None  # noqa: S101  # recurrence_rule is set
        if recurrence.until is None and recurrence.count is None:
            return None
        near = datetime.combine(recurrence.until, time.max) if recurrence.until else None
        *_, last_local = _rule(event, near)
        last = _at(event, last_local)
    if last.end_date is not None:
        return datetime.combine(last.end_date + timedelta(days=1), time.min, tzinfo=UTC)
    return last.end_at
