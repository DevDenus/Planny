"""Busy time as seen from outside: clipped to the window, glued where it touches."""

from datetime import UTC, datetime

from app.calendar.busy import merge_busy


def at(hour: int) -> datetime:
    return datetime(2026, 11, 6, hour, tzinfo=UTC)


WINDOW_START = at(9)
WINDOW_END = at(18)


def test_no_intervals_give_nothing() -> None:
    assert merge_busy([], WINDOW_START, WINDOW_END) == []


def test_disjoint_intervals_stay_apart_and_come_sorted() -> None:
    intervals = [(at(14), at(15)), (at(10), at(11))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == [(at(10), at(11)), (at(14), at(15))]


def test_overlapping_intervals_are_glued() -> None:
    intervals = [(at(9), at(11)), (at(10), at(12))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == [(at(9), at(12))]


def test_touching_intervals_are_glued() -> None:
    intervals = [(at(10), at(11)), (at(11), at(12))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == [(at(10), at(12))]


def test_an_interval_inside_another_is_absorbed() -> None:
    intervals = [(at(9), at(17)), (at(10), at(11))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == [(at(9), at(17))]


def test_an_interval_crossing_the_start_is_clipped_to_it() -> None:
    intervals = [(at(8), at(10))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == [(at(9), at(10))]


def test_an_interval_crossing_the_end_is_clipped_to_it() -> None:
    intervals = [(at(17), at(20))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == [(at(17), at(18))]


def test_an_interval_outside_the_window_is_dropped() -> None:
    intervals = [(at(7), at(8)), (at(19), at(20))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == []


def test_an_interval_that_only_touches_the_window_edge_is_dropped() -> None:
    intervals = [(at(7), at(9)), (at(18), at(20))]

    assert merge_busy(intervals, WINDOW_START, WINDOW_END) == []


def test_unsorted_input_is_merged_and_left_unchanged() -> None:
    intervals = [(at(15), at(16)), (at(10), at(12)), (at(9), at(11))]
    before = list(intervals)

    merged = merge_busy(intervals, WINDOW_START, WINDOW_END)

    assert merged == [(at(9), at(12)), (at(15), at(16))]
    assert intervals == before
