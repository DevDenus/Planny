"""Turns the model's answer into a card the create and update routes accept.

Nothing the model says is trusted: names are matched against real people and boards, dates are
parsed and checked, and whatever can't be used is dropped with a warning instead of guessed.
"""

import difflib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.assistant.prompt import BoardRef, Context, Person
from app.assistant.schemas import Card, CardKind, EventCard, TaskCard
from app.calendar.schemas import (
    LAST_SERIES_DAY,
    MAX_REMINDER_MINUTES,
    MAX_REMINDERS,
    MAX_SERIES_COUNT,
    RecurrenceInput,
)

TITLE_LIMIT = 200
CHECKLIST_LIMIT = 30
CHECKLIST_TEXT_LIMIT = 500
LOCATION_LIMIT = 500
DESCRIPTION_LIMIT = 20000
REPLY_LIMIT = 500
DEFAULT_EVENT_LENGTH = timedelta(hours=1)
FALLBACK_TITLE = {"task": "Новая задача", "event": "Новое событие"}
SELF_WORDS = {"я", "мне", "меня", "мной", "себе", "себя"}


@dataclass
class Outcome:
    """`card` is None only when there was no card and the model found none in the message."""

    card: Card | None
    reply: str
    warnings: list[str] = field(default_factory=list)


def _key(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split())


def _match[T](name: str, options: dict[str, T]) -> T | None:
    """Exact match first, then a single option the name is part of, then a close spelling."""
    key = _key(name)
    if not key:
        return None
    if key in options:
        return options[key]
    partial = [value for option, value in options.items() if key in option.split()]
    if len(partial) == 1:
        return partial[0]
    close = difflib.get_close_matches(key, list(options), n=1, cutoff=0.75)
    return options[close[0]] if close else None


def _person(name: str, ctx: Context) -> Person | None:
    if _key(name) in SELF_WORDS:
        return ctx.me
    return _match(name, {_key(p.name): p for p in ctx.people})


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, str) else ""


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _time(value: Any) -> time | None:
    try:
        return time.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _moment(day: date, at: time, ctx: Context) -> datetime:
    return datetime.combine(day, at, tzinfo=ctx.zone).astimezone(UTC)


def _people(raw: Any, ctx: Context, warnings: list[str]) -> list[Person]:
    found: list[Person] = []
    for name in raw if isinstance(raw, list) else []:
        if not isinstance(name, str) or not name.strip():
            continue
        person = _person(name, ctx)
        if person is None:
            warnings.append(f"Не нашёл «{name.strip()}» среди пользователей.")
        elif person not in found:
            found.append(person)
    return found


def _default_board(ctx: Context) -> BoardRef | None:
    return next((b for b in ctx.boards if b.is_default), ctx.boards[0] if ctx.boards else None)


def _task(raw: dict[str, Any], ctx: Context, warnings: list[str]) -> TaskCard:
    board = _default_board(ctx)
    if isinstance(raw.get("board"), str) and raw["board"].strip():
        named = _match(raw["board"], {_key(b.name): b for b in ctx.boards})
        if named is None:
            warnings.append(f"Не нашёл доску «{raw['board'].strip()}», выбрал личную.")
        else:
            board = named
    column_id = None
    if board and isinstance(raw.get("column"), str) and raw["column"].strip():
        column = _match(raw["column"], {_key(c.name): c for c in board.columns})
        if column is None:
            warnings.append(f"На доске «{board.name}» нет колонки «{raw['column'].strip()}».")
        else:
            column_id = column.id

    assignee_ids = []
    for person in _people(raw.get("people"), ctx, warnings):
        if board and person.id not in board.member_ids:
            warnings.append(f"{person.name} не участник доски «{board.name}», не назначил.")
        else:
            assignee_ids.append(person.id)

    items = raw.get("checklist")
    checklist = [
        text
        for item in (items if isinstance(items, list) else [])[:CHECKLIST_LIMIT]
        if (text := _text(item, CHECKLIST_TEXT_LIMIT))
    ]
    priority = raw.get("priority")
    day, at = _date(raw.get("date")), _time(raw.get("time"))
    if at is not None and day is None:
        day = ctx.now.date()
    return TaskCard(
        title=_text(raw.get("title"), TITLE_LIMIT) or FALLBACK_TITLE["task"],
        description=_text(raw.get("description"), DESCRIPTION_LIMIT) or None,
        board_id=board.id if board else None,
        column_id=column_id,
        priority=priority if priority in (1, 2, 3, 4) else 3,
        assignee_ids=assignee_ids,
        checklist=checklist,
        due_date=day if at is None else None,
        due_at=_moment(day, at, ctx) if day and at else None,
    )


def _recurrence(raw: dict[str, Any], start: date, warnings: list[str]) -> RecurrenceInput | None:
    freq = raw.get("repeat")
    if freq not in ("daily", "weekly", "monthly"):
        return None
    until = _date(raw.get("repeat_until"))
    if until is not None and not start <= until <= LAST_SERIES_DAY:
        warnings.append("Не понял, до какого дня повторять, оставил повтор без конца.")
        until = None
    count = raw.get("repeat_count")
    if until is not None or not isinstance(count, int) or not 1 <= count <= MAX_SERIES_COUNT:
        count = None
    return RecurrenceInput(freq=freq, until=until, count=count)


def _reminders(raw: Any) -> list[int]:
    values = {
        value
        for value in (raw if isinstance(raw, list) else [])
        if isinstance(value, int) and 0 <= value <= MAX_REMINDER_MINUTES
    }
    return sorted(values)[:MAX_REMINDERS]


def _event(raw: dict[str, Any], ctx: Context, warnings: list[str]) -> EventCard:
    day = _date(raw.get("date"))
    if day is None:
        day = ctx.now.date()
        warnings.append("Не понял дату, поставил сегодня.")
    at, end_day, end_at = (
        _time(raw.get("time")),
        _date(raw.get("end_date")),
        _time(raw.get("end_time")),
    )
    times: dict[str, Any]
    if all_day := bool(raw.get("all_day")) or at is None:
        last = end_day if end_day is not None and end_day >= day else day
        times = {"start_date": day, "end_date": last}
    else:
        start = _moment(day, at, ctx)
        if end_at is None:
            end = start + DEFAULT_EVENT_LENGTH
        else:
            end = _moment(end_day or day, end_at, ctx)
            if end <= start and end_day is None:
                end += timedelta(days=1)  # 23:00–01:00 ends the next day
            if end <= start:
                warnings.append("Конец раньше начала, поставил час.")
                end = start + DEFAULT_EVENT_LENGTH
        times = {"start_at": start, "end_at": end}

    participants = [p.id for p in _people(raw.get("people"), ctx, warnings) if p.id != ctx.me.id]
    return EventCard(
        title=_text(raw.get("title"), TITLE_LIMIT) or FALLBACK_TITLE["event"],
        description=_text(raw.get("description"), DESCRIPTION_LIMIT) or None,
        location=_text(raw.get("location"), LOCATION_LIMIT) or None,
        all_day=all_day,
        timezone=ctx.timezone,
        participant_ids=participants,
        recurrence=_recurrence(raw, day, warnings),
        reminder_minutes=_reminders(raw.get("reminders")),
        **times,
    )


def normalize(
    raw: dict[str, Any], ctx: Context, current: Card | None, locked: CardKind | None
) -> Outcome:
    """`current` is the card before this message, `locked` the kind of an already created one,
    which a message can't change."""
    warnings: list[str] = []
    reply = _text(raw.get("reply"), REPLY_LIMIT)
    kind = raw.get("kind")
    if kind not in ("task", "event"):
        # Nothing to fill, so the card stays as it was rather than be wiped by empty fields.
        return Outcome(current, reply or "Не понял, что нужно сделать. Опишите задачу или событие.")
    if locked is not None and kind != locked:
        warnings.append("Тип карточки после создания не меняется.")
        kind = locked
    card = _task(raw, ctx, warnings) if kind == "task" else _event(raw, ctx, warnings)
    return Outcome(card, reply or "Готово, проверьте карточку.", warnings)
