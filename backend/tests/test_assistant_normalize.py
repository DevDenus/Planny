"""How the answer of the model becomes a card. Pure: no database, no model."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.assistant.normalize import normalize
from app.assistant.prompt import BoardRef, Column, Context, Person
from app.assistant.schemas import EventCard, TaskCard
from app.calendar.schemas import MAX_REMINDER_MINUTES

DENIS = Person(uuid4(), "Денис")
MARIA = Person(uuid4(), "Мария")
PETR = Person(uuid4(), "Пётр")


def board(name: str, members: set[UUID], *, is_default: bool = False) -> BoardRef:
    return BoardRef(
        id=uuid4(),
        name=name,
        is_default=is_default,
        member_ids=frozenset(members),
        columns=(
            Column(uuid4(), "Сделать", False),
            Column(uuid4(), "В работе", False),
            Column(uuid4(), "Готово", True),
        ),
    )


PERSONAL = board("Личное", {DENIS.id}, is_default=True)
HOME = board("Дом", {DENIS.id, MARIA.id})
REPAIR = board("Ремонт", {DENIS.id, MARIA.id, PETR.id})

CTX = Context(
    now=datetime(2026, 11, 9, 10, 30, tzinfo=ZoneInfo("Europe/Moscow")),
    timezone="Europe/Moscow",
    me=DENIS,
    people=(DENIS, MARIA, PETR),
    boards=(PERSONAL, HOME, REPAIR),
)


def answer(**fields: Any) -> dict[str, Any]:
    """A complete answer in the shape of ANSWER_SCHEMA, with only `fields` filled in."""
    raw: dict[str, Any] = {
        "kind": "task",
        "title": "Купить молоко",
        "description": "",
        "board": None,
        "column": None,
        "people": [],
        "priority": 3,
        "checklist": [],
        "all_day": False,
        "date": None,
        "time": None,
        "end_date": None,
        "end_time": None,
        "location": None,
        "repeat": "none",
        "repeat_until": None,
        "repeat_count": None,
        "reminders": [],
        "reply": "Готово",
    }
    return raw | fields


def task(**fields: Any) -> tuple[TaskCard, list[str]]:
    outcome = normalize(answer(**fields), CTX, None, None)
    assert isinstance(outcome.card, TaskCard)
    return outcome.card, outcome.warnings


def event(**fields: Any) -> tuple[EventCard, list[str]]:
    outcome = normalize(answer(kind="event", title="Ужин", **fields), CTX, None, None)
    assert isinstance(outcome.card, EventCard)
    return outcome.card, outcome.warnings


def test_a_task_gets_its_board_column_and_assignee_by_name() -> None:
    card, warnings = task(board="дом", column="в работе", people=["Мария"], priority=2)

    assert card.board_id == HOME.id
    assert card.column_id == HOME.columns[1].id
    assert card.assignee_ids == [MARIA.id]
    assert card.priority == 2
    assert warnings == []


def test_an_assignee_who_is_not_on_the_board_is_dropped_with_a_warning() -> None:
    card, warnings = task(people=["Мария"])

    assert card.board_id == PERSONAL.id
    assert card.assignee_ids == []
    assert len(warnings) == 1
    assert "Мария" in warnings[0]


def test_an_unknown_board_falls_back_to_the_default_one() -> None:
    card, warnings = task(board="Гараж", column="Сделать")

    assert card.board_id == PERSONAL.id
    assert card.column_id == PERSONAL.columns[0].id
    assert any("Гараж" in warning for warning in warnings)


def test_an_unknown_person_is_reported() -> None:
    card, warnings = task(people=["Василий"])

    assert card.assignee_ids == []
    assert any("Василий" in warning for warning in warnings)


def test_me_means_the_user() -> None:
    card, warnings = task(people=["мне"])

    assert card.assignee_ids == [DENIS.id]
    assert warnings == []


def test_a_date_without_time_is_a_due_date() -> None:
    card, _ = task(date="2026-11-13")

    assert card.due_date == date(2026, 11, 13)
    assert card.due_at is None


def test_a_date_with_time_is_a_moment_in_utc() -> None:
    card, _ = task(date="2026-11-13", time="18:30")

    assert card.due_at == datetime(2026, 11, 13, 15, 30, tzinfo=UTC)
    assert card.due_date is None


def test_a_time_without_a_date_is_today() -> None:
    card, _ = task(time="18:00")

    assert card.due_at == datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def test_a_timed_event_lasts_an_hour_by_default() -> None:
    card, _ = event(date="2026-11-10", time="19:00")

    assert not card.all_day
    assert card.start_at == datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    assert card.end_at == datetime(2026, 11, 10, 17, 0, tzinfo=UTC)
    assert card.start_date is None
    assert card.timezone == "Europe/Moscow"


def test_an_end_time_before_the_start_means_the_next_day() -> None:
    card, warnings = event(date="2026-11-10", time="23:00", end_time="01:00")

    assert card.start_at == datetime(2026, 11, 10, 20, 0, tzinfo=UTC)
    assert card.end_at == datetime(2026, 11, 10, 22, 0, tzinfo=UTC)
    assert warnings == []


def test_an_event_without_time_is_all_day() -> None:
    card, _ = event(date="2026-11-10")

    assert card.all_day
    assert (card.start_date, card.end_date) == (date(2026, 11, 10), date(2026, 11, 10))
    assert card.start_at is None


def test_an_all_day_end_before_the_start_becomes_the_start() -> None:
    card, _ = event(all_day=True, date="2026-11-12", end_date="2026-11-10")

    assert (card.start_date, card.end_date) == (date(2026, 11, 12), date(2026, 11, 12))


def test_participants_leave_out_the_user() -> None:
    card, _ = event(date="2026-11-10", time="19:00", people=["Денис", "Мария"])

    assert card.participant_ids == [MARIA.id]


def test_a_weekly_series_until_a_day() -> None:
    card, warnings = event(
        date="2026-11-10", time="19:00", repeat="weekly", repeat_until="2026-12-29"
    )

    assert card.recurrence is not None
    assert (card.recurrence.freq, card.recurrence.until, card.recurrence.count) == (
        "weekly",
        date(2026, 12, 29),
        None,
    )
    assert warnings == []


def test_a_series_for_a_number_of_repeats() -> None:
    card, _ = event(date="2026-11-10", time="19:00", repeat="weekly", repeat_count=5)

    assert card.recurrence is not None
    assert (card.recurrence.until, card.recurrence.count) == (None, 5)


def test_a_series_ending_before_it_starts_loses_its_end() -> None:
    card, warnings = event(
        date="2026-11-10", time="19:00", repeat="weekly", repeat_until="2026-11-01"
    )

    assert card.recurrence is not None
    assert (card.recurrence.until, card.recurrence.count) == (None, None)
    assert len(warnings) == 1


def test_reminders_are_unique_sorted_and_limited_to_five() -> None:
    card, _ = event(
        date="2026-11-10",
        time="19:00",
        reminders=[60, 10, 60, 5, 0, 30, 1440, -1, MAX_REMINDER_MINUTES + 1],
    )

    assert card.reminder_minutes == [0, 5, 10, 30, 60]


def test_reminders_out_of_range_are_dropped() -> None:
    card, _ = event(date="2026-11-10", time="19:00", reminders=[-1, 15, MAX_REMINDER_MINUTES + 1])

    assert card.reminder_minutes == [15]


def test_no_kind_and_no_card_gives_no_card() -> None:
    outcome = normalize(answer(kind="none", reply="Что нужно сделать?"), CTX, None, None)

    assert outcome.card is None
    assert outcome.reply == "Что нужно сделать?"


def test_no_kind_keeps_the_current_card() -> None:
    current = TaskCard(title="Купить хлеб", board_id=PERSONAL.id)

    outcome = normalize(answer(kind="none", title="", reply="Не понял"), CTX, current, None)

    assert outcome.card is current


def test_a_created_card_keeps_its_kind() -> None:
    outcome = normalize(
        answer(kind="event", date="2026-11-10", time="19:00"), CTX, TaskCard(title="Х"), "task"
    )

    assert isinstance(outcome.card, TaskCard)
    assert len(outcome.warnings) == 1


def test_the_checklist_is_trimmed_and_empty_items_are_dropped() -> None:
    card, _ = task(checklist=["  молоко ", "", "   ", "хлеб"])

    assert card.checklist == ["молоко", "хлеб"]


def test_a_checklist_that_is_not_a_list_is_ignored() -> None:
    card, _ = task(checklist="молоко, хлеб")

    assert card.checklist == []
