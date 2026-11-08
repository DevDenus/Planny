"""Fixed context and cases for the manual assistant evaluation (scripts/assistant_eval.py).

Checks work on a View: names instead of ids, local times instead of UTC.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid5

from app.assistant.prompt import BoardRef, Column, Context, Person
from app.assistant.schemas import Card, TaskCard

ZONE = "Europe/Moscow"
NAMESPACE = UUID("6f0d7a54-3c1e-4b8a-9a53-5a1c2d3e4f50")
COLUMNS = ("Сделать", "В работе", "Готово")


def _id(name: str) -> UUID:
    return uuid5(NAMESPACE, name)


def _board(name: str, members: tuple[str, ...], is_default: bool = False) -> BoardRef:
    columns = tuple(Column(_id(f"{name}/{c}"), c, is_done=(c == "Готово")) for c in COLUMNS)
    return BoardRef(
        id=_id(f"board/{name}"),
        name=name,
        is_default=is_default,
        member_ids=frozenset(_id(f"person/{m}") for m in members),
        columns=columns,
    )


def make_context() -> Context:
    from zoneinfo import ZoneInfo

    people = tuple(Person(_id(f"person/{n}"), n) for n in ("Денис", "Мария", "Пётр"))
    return Context(
        now=datetime(2026, 11, 9, 10, 30, tzinfo=ZoneInfo(ZONE)),
        timezone=ZONE,
        me=people[0],
        people=people,
        boards=(
            _board("Личное", ("Денис",), is_default=True),
            _board("Дом", ("Денис", "Мария")),
            _board("Ремонт", ("Денис", "Мария", "Пётр")),
        ),
    )


@dataclass(frozen=True)
class View:
    kind: str  # "task", "event" or "none"
    title: str = ""
    board: str | None = None
    column: str | None = None
    people: frozenset[str] = frozenset()  # assignees, or participants without the user
    priority: int | None = None
    checklist: tuple[str, ...] = ()
    due_date: str | None = None
    due_at: str | None = None  # local "YYYY-MM-DD HH:MM"
    all_day: bool = False
    start: str | None = None  # local "YYYY-MM-DD HH:MM"
    end: str | None = None
    start_date: str | None = None
    location: str | None = None
    repeat: str | None = None
    repeat_until: str | None = None
    reminders: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()


def to_view(card: Card | None, ctx: Context, warnings: list[str]) -> View:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(ctx.timezone)
    names = {p.id: p.name for p in ctx.people}

    def local(moment: datetime | None) -> str | None:
        return moment.astimezone(zone).strftime("%Y-%m-%d %H:%M") if moment else None

    def iso(day: date | None) -> str | None:
        return day.isoformat() if day else None

    if card is None:
        return View(kind="none", warnings=tuple(warnings))
    if isinstance(card, TaskCard):
        board = next((b for b in ctx.boards if b.id == card.board_id), None)
        column = board and next((c for c in board.columns if c.id == card.column_id), None)
        return View(
            kind="task",
            title=card.title,
            board=board.name if board else None,
            column=column.name if column else None,
            people=frozenset(names[i] for i in card.assignee_ids if i in names),
            priority=card.priority,
            checklist=tuple(card.checklist),
            due_date=iso(card.due_date),
            due_at=local(card.due_at),
            warnings=tuple(warnings),
        )
    rec = card.recurrence
    return View(
        kind="event",
        title=card.title,
        people=frozenset(names[i] for i in card.participant_ids if i in names and i != ctx.me.id),
        all_day=card.all_day,
        start=local(card.start_at),
        end=local(card.end_at),
        start_date=iso(card.start_date),
        location=card.location,
        repeat=rec.freq if rec else None,
        repeat_until=iso(rec.until) if rec else None,
        reminders=tuple(card.reminder_minutes),
        warnings=tuple(warnings),
    )


Check = tuple[str, Callable[[View], bool]]


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def has(field_name: str, stem: str) -> Check:
    """The text field (or any list item) contains the stem."""

    def check(v: View) -> bool:
        value: Any = getattr(v, field_name)
        if value is None:
            return False
        items = value if isinstance(value, tuple) else (value,)
        return any(_norm(stem) in _norm(i) for i in items)

    return (f"{field_name}~{stem}", check)


def eq(field_name: str, expected: object) -> Check:
    return (field_name, lambda v: getattr(v, field_name) == expected)


def people(*names: str) -> Check:
    return ("people", lambda v: v.people == frozenset(names))


def kind(expected: str) -> Check:
    return eq("kind", expected)


def _initial_case14(ctx: Context) -> Card:
    from zoneinfo import ZoneInfo

    return TaskCard(
        title="Оплатить интернет",
        board_id=_id("board/Личное"),
        due_at=datetime(2026, 11, 10, 18, 0, tzinfo=ZoneInfo(ZONE)),
    )


@dataclass(frozen=True)
class Case:
    id: int
    turns: tuple[str, ...]
    checks: tuple[Check, ...]
    locked: str | None = None
    initial: Callable[[Context], Card] | None = None
    # Stems (regex alternatives) expected in the transcript of the last turn; None: no voice run.
    keywords: tuple[str, ...] | None = None
    notes: str = field(default="", compare=False)

    @property
    def text(self) -> str:
        return self.turns[-1]


_C6 = "Завтра в семь вечера ужин с Машей и Петей, напомни за час"
_C1 = "Купить молоко до пятницы"
_C4 = "Поставь на доску Ремонт задачу для Пети покрасить стены в спальне, срочно, до 20 ноября"

CASES: tuple[Case, ...] = (
    Case(
        1,
        (_C1,),
        (kind("task"), has("title", "молок"), eq("due_date", "2026-11-13"), eq("due_at", None)),
        keywords=("молок", "пятниц"),
    ),
    Case(
        2,
        ("Оплатить интернет завтра до шести вечера",),
        (kind("task"), eq("due_at", "2026-11-10 18:00")),
        keywords=("оплат", "интернет", "завтра", "шест|18"),
    ),
    Case(
        3,
        ("Сходить в магазин: хлеб, яйца, сыр и помидоры",),
        (
            kind("task"),
            ("checklist_len", lambda v: len(v.checklist) == 4),
            has("checklist", "хлеб"),
            has("checklist", "яйц"),
            has("checklist", "сыр"),
            has("checklist", "помидор"),
        ),
        keywords=("магазин", "хлеб", "яйц", "сыр", "помидор"),
    ),
    Case(
        4,
        (_C4,),
        (
            kind("task"),
            eq("board", "Ремонт"),
            people("Пётр"),
            eq("priority", 1),
            eq("due_date", "2026-11-20"),
        ),
        keywords=("ремонт", "пет", "покрас", "стен", "спальн", "срочно", "20"),
    ),
    Case(
        5,
        ("На доске Дом в колонку В работе: Маше разобрать шкаф",),
        (kind("task"), eq("board", "Дом"), eq("column", "В работе"), people("Мария")),
        keywords=("дом", "работе", "маш", "разобрать", "шкаф"),
    ),
    Case(
        6,
        (_C6,),
        (
            kind("event"),
            eq("start", "2026-11-10 19:00"),
            people("Мария", "Пётр"),
            eq("reminders", (60,)),
            eq("all_day", False),
        ),
        keywords=("ужин", "маш", "пет", "семь|19", "час"),
    ),
    Case(
        7,
        ("В субботу на дачу на весь день с Марией",),
        (kind("event"), eq("all_day", True), eq("start_date", "2026-11-14"), people("Мария")),
        keywords=("суббот", "дач", "весь день", "мари"),
    ),
    Case(
        8,
        ("Каждый вторник в 18:30 бассейн до конца года",),
        (
            kind("event"),
            eq("start", "2026-11-17 18:30"),
            eq("repeat", "weekly"),
            eq("repeat_until", "2026-12-31"),
        ),
        keywords=("вторник", "бассейн", "конца года", "18"),
    ),
    Case(
        9,
        ("Встреча с врачом в четверг с 15:00 до 16:30 в поликлинике на Ленина",),
        (
            kind("event"),
            eq("start", "2026-11-12 15:00"),
            eq("end", "2026-11-12 16:30"),
            has("location", "Ленина"),
        ),
        keywords=("врач", "четверг", "15|трех|три", "16|четыр", "поликлиник", "ленина"),
    ),
    Case(
        10,
        (_C6, "нет, не завтра, а в субботу, и без Пети"),
        (
            kind("event"),
            eq("start", "2026-11-14 19:00"),
            people("Мария"),
            eq("reminders", (60,)),
        ),
        keywords=("не завтра", "суббот", "без пет"),
    ),
    Case(
        11,
        (_C1, "добавь в список ещё хлеб и сделай срочной"),
        (
            kind("task"),
            has("checklist", "хлеб"),
            eq("priority", 1),
            eq("due_date", "2026-11-13"),
        ),
        keywords=("добавь", "список", "хлеб", "срочной|срочно"),
    ),
    Case(
        12,
        (_C4, "перенеси на доску Дом"),
        (
            kind("task"),
            eq("board", "Дом"),
            people(),
            (
                "warning~Пётр",
                lambda v: any("петр" in _norm(w) for w in v.warnings),
            ),
        ),
    ),
    Case(
        13,
        ("Завтра в 10 созвон с бухгалтером", "сделай это задачей"),
        (kind("task"), eq("due_at", "2026-11-10 10:00")),
    ),
    Case(
        14,
        ("перенеси на послезавтра",),
        (kind("task"), eq("due_at", "2026-11-11 18:00")),
        locked="task",
        initial=_initial_case14,
    ),
    Case(15, ("привет, как дела?",), (kind("none"),)),
)
