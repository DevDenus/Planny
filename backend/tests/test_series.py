"""AC-08 and the rules of a series, checked on the pure functions: no database, no API."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar.models import Event
from app.calendar.series import (
    Occurrence,
    Recurrence,
    build_rule,
    closest_distance,
    last_started,
    next_occurrence,
    occurrences_in,
    parse_rule,
    series_end,
    start_moment,
)
from app.core.period import Period, period_of
from app.reminders.service import next_fire

MOSCOW = ZoneInfo("Europe/Moscow")
NEW_YORK = ZoneInfo("America/New_York")
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


def timed(
    start_at: datetime,
    end_at: datetime,
    rule: str | None = None,
    timezone: str = "Europe/Moscow",
) -> Event:
    return Event(
        all_day=False, start_at=start_at, end_at=end_at, timezone=timezone, recurrence_rule=rule
    )


def dated(
    start_date: date,
    end_date: date,
    rule: str | None = None,
    timezone: str = "Europe/Moscow",
) -> Event:
    return Event(
        all_day=True,
        start_date=start_date,
        end_date=end_date,
        timezone=timezone,
        recurrence_rule=rule,
    )


def moscow_days(first: date, last: date) -> Period:
    """The whole days from `first` to `last` in Moscow, both included."""
    start = datetime.combine(first, time.min, tzinfo=MOSCOW)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=MOSCOW)
    return period_of(start, end, MOSCOW)


def local_starts(found: list[Occurrence]) -> list[datetime]:
    """When each occurrence with a time starts, on the clock in Moscow."""
    starts = [occurrence.start_at for occurrence in found]
    assert None not in starts
    return [start.astimezone(MOSCOW) for start in starts if start is not None]


# Rules


def test_no_recurrence_is_no_rule() -> None:
    assert build_rule(None) is None
    assert parse_rule(None) is None


def test_a_series_without_an_end_is_written_as_its_frequency() -> None:
    assert build_rule(Recurrence("monthly")) == "FREQ=MONTHLY"
    assert parse_rule("FREQ=MONTHLY") == Recurrence("monthly")


def test_an_until_date_is_written_as_the_last_second_of_that_local_day() -> None:
    recurrence = Recurrence("monthly", until=date(2027, 12, 31))

    assert build_rule(recurrence) == "FREQ=MONTHLY;UNTIL=20271231T235959"
    assert parse_rule("FREQ=MONTHLY;UNTIL=20271231T235959") == recurrence


def test_a_count_is_written_as_the_number_of_repeats() -> None:
    recurrence = Recurrence("weekly", count=4)

    assert build_rule(recurrence) == "FREQ=WEEKLY;COUNT=4"
    assert parse_rule("FREQ=WEEKLY;COUNT=4") == recurrence


# Expansion


def test_ac_08_the_first_of_the_month_at_one_am_in_moscow_stays_on_the_first() -> None:
    # 1 January 2027, 01:00 in Moscow, is 31 December 2026 22:00 in UTC.
    event = timed(
        datetime(2026, 12, 31, 22, tzinfo=UTC),
        datetime(2026, 12, 31, 23, tzinfo=UTC),
        "FREQ=MONTHLY",
    )

    found = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 12, 31)))

    assert local_starts(found) == [
        datetime(2027, month, 1, 1, tzinfo=MOSCOW) for month in range(1, 13)
    ]


def test_ac_08_the_31st_is_only_in_the_months_that_have_one() -> None:
    event = timed(
        datetime(2027, 1, 31, 7, tzinfo=UTC),
        datetime(2027, 1, 31, 8, tzinfo=UTC),
        "FREQ=MONTHLY",
    )

    found = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 12, 31)))

    assert local_starts(found) == [
        datetime(2027, month, 31, 10, tzinfo=MOSCOW) for month in (1, 3, 5, 7, 8, 10, 12)
    ]


def test_ac_08_an_endless_series_from_2026_repeats_in_2090() -> None:
    # Friday 6 November 2026, 10:00 in Moscow.
    start = datetime(2026, 11, 6, 7, tzinfo=UTC)
    week = moscow_days(date(2090, 3, 6), date(2090, 3, 12))

    daily = occurrences_in(timed(start, start + HOUR, "FREQ=DAILY"), week)
    weekly = occurrences_in(timed(start, start + HOUR, "FREQ=WEEKLY"), week)
    monthly = occurrences_in(timed(start, start + HOUR, "FREQ=MONTHLY"), week)

    assert local_starts(daily) == [
        datetime(2090, 3, day, 10, tzinfo=MOSCOW) for day in range(6, 13)
    ]
    assert local_starts(weekly) == [datetime(2090, 3, 10, 10, tzinfo=MOSCOW)]
    assert local_starts(monthly) == [datetime(2090, 3, 6, 10, tzinfo=MOSCOW)]


def test_ac_08_a_weekly_series_stays_on_its_weekday_far_away() -> None:
    start = datetime(2026, 11, 6, 7, tzinfo=UTC)

    found = occurrences_in(
        timed(start, start + HOUR, "FREQ=WEEKLY"), moscow_days(date(2090, 3, 1), date(2090, 3, 28))
    )

    assert [moment.date() for moment in local_starts(found)] == [
        date(2090, 3, 3),
        date(2090, 3, 10),
        date(2090, 3, 17),
        date(2090, 3, 24),
    ]


def test_ac_08_a_daily_series_gives_its_occurrence_in_the_year_5000() -> None:
    start = datetime(2026, 11, 6, 7, tzinfo=UTC)

    found = occurrences_in(
        timed(start, start + HOUR, "FREQ=DAILY"), moscow_days(date(5000, 6, 10), date(5000, 6, 10))
    )

    assert local_starts(found) == [datetime(5000, 6, 10, 10, tzinfo=MOSCOW)]


def test_an_until_date_keeps_the_occurrence_on_that_day_and_nothing_after() -> None:
    # Weekly on Mondays at 10:00 in Moscow: 4, 11 and 18 January 2027.
    start = datetime(2027, 1, 4, 7, tzinfo=UTC)
    event = timed(start, start + HOUR, "FREQ=WEEKLY;UNTIL=20270118T235959")

    whole = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 2, 28)))
    after = occurrences_in(event, moscow_days(date(2027, 1, 19), date(2027, 2, 28)))

    assert local_starts(whole) == [datetime(2027, 1, day, 10, tzinfo=MOSCOW) for day in (4, 11, 18)]
    assert after == []


def test_a_count_gives_exactly_that_many_occurrences_and_then_none() -> None:
    start = datetime(2027, 1, 4, 7, tzinfo=UTC)
    event = timed(start, start + HOUR, "FREQ=WEEKLY;COUNT=4")

    found = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 12, 31)))

    assert local_starts(found) == [
        datetime(2027, 1, 4, 10, tzinfo=MOSCOW) + timedelta(weeks=week) for week in range(4)
    ]
    assert occurrences_in(event, moscow_days(date(2027, 2, 1), date(2027, 2, 28))) == []


def test_a_count_on_the_31st_uses_only_the_months_that_have_one() -> None:
    start = datetime(2027, 1, 31, 7, tzinfo=UTC)
    event = timed(start, start + HOUR, "FREQ=MONTHLY;COUNT=3")

    found = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 12, 31)))

    assert local_starts(found) == [
        datetime(2027, 1, 31, 10, tzinfo=MOSCOW),
        datetime(2027, 3, 31, 10, tzinfo=MOSCOW),
        datetime(2027, 5, 31, 10, tzinfo=MOSCOW),
    ]


# Window edges


def test_an_occurrence_that_ends_exactly_when_the_period_starts_is_not_in_it() -> None:
    event = timed(
        datetime(2027, 1, 10, 10, tzinfo=MOSCOW), datetime(2027, 1, 10, 11, tzinfo=MOSCOW)
    )
    period = period_of(
        datetime(2027, 1, 10, 11, tzinfo=MOSCOW), datetime(2027, 1, 10, 12, tzinfo=MOSCOW), MOSCOW
    )

    assert occurrences_in(event, period) == []


def test_an_occurrence_that_starts_before_the_period_and_ends_in_it_is_in_it() -> None:
    event = timed(
        datetime(2027, 1, 10, 10, tzinfo=MOSCOW), datetime(2027, 1, 10, 12, tzinfo=MOSCOW)
    )
    period = period_of(
        datetime(2027, 1, 10, 11, tzinfo=MOSCOW), datetime(2027, 1, 10, 13, tzinfo=MOSCOW), MOSCOW
    )

    assert local_starts(occurrences_in(event, period)) == [datetime(2027, 1, 10, 10, tzinfo=MOSCOW)]


def test_an_occurrence_that_starts_exactly_when_the_period_ends_is_not_in_it() -> None:
    event = timed(
        datetime(2027, 1, 10, 13, tzinfo=MOSCOW), datetime(2027, 1, 10, 14, tzinfo=MOSCOW)
    )
    period = period_of(
        datetime(2027, 1, 10, 11, tzinfo=MOSCOW), datetime(2027, 1, 10, 13, tzinfo=MOSCOW), MOSCOW
    )

    assert occurrences_in(event, period) == []


# All-day


def test_ac_08_an_all_day_series_gives_a_pair_of_dates_each_month() -> None:
    event = dated(date(2027, 1, 1), date(2027, 1, 2), "FREQ=MONTHLY")

    found = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 12, 31)))

    assert [(occurrence.start_date, occurrence.end_date) for occurrence in found] == [
        (date(2027, month, 1), date(2027, month, 2)) for month in range(1, 13)
    ]


def test_an_all_day_occurrence_is_found_from_its_second_day() -> None:
    event = dated(date(2027, 1, 1), date(2027, 1, 2), "FREQ=MONTHLY")

    found = occurrences_in(event, moscow_days(date(2027, 2, 2), date(2027, 2, 2)))

    assert [(occurrence.start_date, occurrence.end_date) for occurrence in found] == [
        (date(2027, 2, 1), date(2027, 2, 2))
    ]


def test_an_all_day_occurrence_starts_at_local_midnight_of_its_zone_in_utc() -> None:
    event = dated(date(2027, 1, 1), date(2027, 1, 2), "FREQ=MONTHLY", timezone="Asia/Tokyo")
    [first] = occurrences_in(event, moscow_days(date(2027, 1, 1), date(2027, 1, 1)))

    # Midnight of 1 January in Tokyo is 15:00 of 31 December in UTC.
    assert start_moment(event, first) == datetime(2026, 12, 31, 15, tzinfo=UTC)


# Next and last


def test_the_next_occurrence_of_a_one_off_is_only_one_that_starts_later() -> None:
    start = datetime(2027, 1, 10, 10, tzinfo=MOSCOW)
    event = timed(start, start + HOUR)

    assert next_occurrence(event, start - timedelta(seconds=1)) == Occurrence(
        start_at=start, end_at=start + HOUR
    )
    assert next_occurrence(event, start) is None


def test_the_last_started_one_off_includes_the_moment_it_starts() -> None:
    start = datetime(2027, 1, 10, 10, tzinfo=MOSCOW)
    event = timed(start, start + HOUR)

    assert last_started(event, start) == Occurrence(start_at=start, end_at=start + HOUR)
    assert last_started(event, start - timedelta(seconds=1)) is None


def test_the_next_occurrence_of_a_series_is_strictly_later_than_the_moment() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)
    event = timed(start, start + HOUR, "FREQ=WEEKLY")
    second = start + timedelta(weeks=1)

    assert next_occurrence(event, start) == Occurrence(start_at=second, end_at=second + HOUR)
    assert next_occurrence(event, start - timedelta(seconds=1)) == Occurrence(
        start_at=start, end_at=start + HOUR
    )


def test_the_last_started_occurrence_of_a_series_includes_the_moment_it_starts() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)
    event = timed(start, start + HOUR, "FREQ=WEEKLY")
    second = start + timedelta(weeks=1)

    assert last_started(event, second) == Occurrence(start_at=second, end_at=second + HOUR)
    assert last_started(event, second - timedelta(seconds=1)) == Occurrence(
        start_at=start, end_at=start + HOUR
    )


def test_a_finished_series_has_no_next_occurrence() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)
    after_the_end = start + timedelta(weeks=5)

    counted = timed(start, start + HOUR, "FREQ=WEEKLY;COUNT=2")
    dated_end = timed(start, start + HOUR, "FREQ=WEEKLY;UNTIL=20270118T235959")

    assert next_occurrence(counted, after_the_end) is None
    assert next_occurrence(dated_end, after_the_end) is None


def test_the_last_started_occurrence_of_a_finished_series_is_its_last_one() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)
    long_after = datetime(2027, 3, 1, tzinfo=UTC)

    daily = timed(start, start + HOUR, "FREQ=DAILY;UNTIL=20270110T235959")
    weekly = timed(start, start + HOUR, "FREQ=WEEKLY;UNTIL=20270118T235959")

    assert last_started(daily, long_after) == Occurrence(
        start_at=start + timedelta(days=6), end_at=start + timedelta(days=6) + HOUR
    )
    assert last_started(weekly, long_after) == Occurrence(
        start_at=start + timedelta(weeks=2), end_at=start + timedelta(weeks=2) + HOUR
    )


# Series end


def test_a_series_without_an_end_has_no_series_end() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)

    assert series_end(timed(start, start + HOUR, "FREQ=DAILY")) is None


def test_a_counted_series_ends_with_its_last_occurrence() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)

    event = timed(start, start + HOUR, "FREQ=WEEKLY;COUNT=4")

    assert series_end(event) == datetime(2027, 1, 25, 11, tzinfo=MOSCOW)


def test_a_series_until_a_date_ends_with_the_occurrence_on_that_date() -> None:
    start = datetime(2027, 1, 4, 10, tzinfo=MOSCOW)

    event = timed(start, start + HOUR, "FREQ=WEEKLY;UNTIL=20270118T235959")

    assert series_end(event) == datetime(2027, 1, 18, 11, tzinfo=MOSCOW)


def test_a_one_off_ends_when_it_ends() -> None:
    start = datetime(2027, 1, 10, 10, tzinfo=MOSCOW)

    assert series_end(timed(start, start + HOUR)) == datetime(2027, 1, 10, 11, tzinfo=MOSCOW)


def test_an_all_day_event_ends_at_midnight_utc_after_its_last_day() -> None:
    assert series_end(dated(date(2027, 1, 1), date(2027, 1, 2))) == datetime(2027, 1, 3, tzinfo=UTC)
    assert series_end(dated(date(2027, 1, 1), date(2027, 1, 2), "FREQ=MONTHLY;COUNT=2")) == (
        datetime(2027, 2, 3, tzinfo=UTC)
    )


# Clock changes


def test_an_occurrence_in_a_skipped_hour_is_found_at_its_real_moment() -> None:
    # 02:30 doesn't exist in New York on 14 March 2027: the weekly event falls on 07:30 UTC.
    first = datetime(2027, 3, 7, 7, 30, tzinfo=UTC)
    moment = first + timedelta(days=7)
    event = timed(first, first + 10 * MINUTE, "FREQ=WEEKLY", "America/New_York")
    window = period_of(moment - 10 * MINUTE, moment + 20 * MINUTE, NEW_YORK)

    assert [item.start_at for item in occurrences_in(event, window)] == [moment]
    upcoming = next_occurrence(event, moment - 20 * MINUTE)
    assert upcoming is not None
    assert upcoming.start_at == moment
    assert next_fire(event, 20, moment - 45 * MINUTE) == moment - 20 * MINUTE
    started = last_started(event, moment + 10 * MINUTE)
    assert started is not None
    assert started.start_at == moment
    previous = last_started(event, moment - 20 * MINUTE)
    assert previous is not None
    assert previous.start_at == first


def test_an_occurrence_in_a_repeated_hour_stays_behind_a_later_moment() -> None:
    # 01:30 comes twice in New York on 7 November 2027, and the rule takes the first: 05:30 UTC.
    first = datetime(2027, 10, 31, 5, 30, tzinfo=UTC)
    moment = first + timedelta(days=7)
    second_pass = moment + 45 * MINUTE  # 01:15 on the clock again, after the clocks went back.
    event = timed(first, first + 10 * MINUTE, "FREQ=WEEKLY", "America/New_York")
    window = period_of(moment - 10 * MINUTE, second_pass, NEW_YORK)

    assert [item.start_at for item in occurrences_in(event, window)] == [moment]
    upcoming = next_occurrence(event, second_pass)
    assert upcoming is not None
    assert upcoming.start_at == datetime(2027, 11, 14, 6, 30, tzinfo=UTC)
    started = last_started(event, second_pass)
    assert started is not None
    assert started.start_at == moment


# Closeness


def test_the_closest_occurrence_counts_in_both_directions() -> None:
    first = datetime(2030, 1, 1, 10, tzinfo=UTC)
    daily = timed(first, first + HOUR, "FREQ=DAILY")
    finished = timed(first, first + HOUR, "FREQ=DAILY;COUNT=2")
    single = timed(first, first + HOUR)
    ahead = first + timedelta(days=10)

    assert closest_distance(daily, ahead - 2 * HOUR) == 2 * HOUR
    assert closest_distance(daily, ahead + 3 * HOUR) == 3 * HOUR
    assert closest_distance(daily, first - 5 * HOUR) == 5 * HOUR
    assert closest_distance(finished, ahead) == timedelta(days=9)
    assert closest_distance(single, ahead) == timedelta(days=10)
    assert closest_distance(single, first - HOUR) == HOUR
