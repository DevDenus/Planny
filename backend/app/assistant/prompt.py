"""What the language model sees and the shape it must answer in.

The model never handles ids, UTC or date arithmetic: it gets numbered names and a table of the
coming days and answers with names and local dates, which normalize.py turns into a card.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.assistant.schemas import Card, TaskCard

DAYS_AHEAD = 14
MAX_HISTORY = 6
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


@dataclass(frozen=True)
class Person:
    id: UUID
    name: str


@dataclass(frozen=True)
class Column:
    id: UUID
    name: str
    is_done: bool


@dataclass(frozen=True)
class BoardRef:
    id: UUID
    name: str
    is_default: bool
    member_ids: frozenset[UUID]
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class Context:
    """`now` is aware and already in `timezone`. `boards` are the ones the user may write to,
    `people` are the active users, the user included."""

    now: datetime
    timezone: str
    me: Person
    people: tuple[Person, ...]
    boards: tuple[BoardRef, ...]

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


_DATE = {"type": ["string", "null"], "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"}
_TIME = {"type": ["string", "null"], "pattern": r"^[0-9]{2}:[0-9]{2}$"}
_NAME = {"type": ["string", "null"]}

# Order matters: the model writes the fields in this order, so the kind comes first and the
# reply, which sums up the rest, comes last.
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"enum": ["task", "event", "none"]},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "board": _NAME,
        "column": _NAME,
        "people": {"type": "array", "items": {"type": "string"}},
        "priority": {"enum": [1, 2, 3, 4]},
        "checklist": {"type": "array", "items": {"type": "string"}},
        "all_day": {"type": "boolean"},
        "date": _DATE,
        "time": _TIME,
        "end_date": _DATE,
        "end_time": _TIME,
        "location": _NAME,
        "repeat": {"enum": ["none", "daily", "weekly", "monthly"]},
        "repeat_until": _DATE,
        "repeat_count": {"type": ["integer", "null"]},
        "reminders": {"type": "array", "items": {"type": "integer"}},
        "reply": {"type": "string"},
    },
    "required": [
        "kind",
        "title",
        "description",
        "board",
        "column",
        "people",
        "priority",
        "checklist",
        "all_day",
        "date",
        "time",
        "end_date",
        "end_time",
        "location",
        "repeat",
        "repeat_until",
        "repeat_count",
        "reminders",
        "reply",
    ],
    "additionalProperties": False,
}

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "card", "strict": True, "schema": ANSWER_SCHEMA},
}

SYSTEM = """\
Ты помощник семейного планировщика. По сообщению пользователя ты заполняешь ровно одну карточку: \
задачу (kind=task) или событие в календаре (kind=event).

Как выбрать тип:
- event — то, что происходит в конкретное время или в конкретный день: встреча, ужин, врач, \
поездка, день рождения, звонок в 15:00.
- task — то, что нужно сделать: купить, починить, оплатить, позвонить, «до пятницы».
- none — сообщение не про задачу и не про событие, или из него ничего нельзя понять. Тогда \
в reply коротко спроси, что нужно сделать.

Поля:
- title — короткое название без даты, времени и имён, с заглавной буквы. Например «Купить молоко», \
«Ужин с родителями».
- description — подробности, которых нет в других полях. Если их нет — пустая строка.
- people — для задачи это исполнители, для события участники. Пиши имена только в точности из \
списка людей. «Я», «мне», «меня» — это пользователь, его имя помечено в списке. Если человека \
нет в списке, всё равно напиши имя как услышал. Если никто не назван, оставь список пустым.
- board и column — только для задачи и только если пользователь назвал доску или колонку. \
Пиши название в точности из списка досок. Иначе null.
- priority: 1 — срочно, 2 — важно, 3 — обычно, 4 — когда-нибудь.
- checklist — пункты, если пользователь перечислил несколько вещей, которые нужно сделать или \
купить. Не повторяй в нём название. Иначе пусто.
- date и time — для задачи это срок, для события начало. Дату бери из таблицы дней, сам не \
считай. «В пятницу» — ближайшая пятница после сегодняшнего дня. Время в 24-часовом формате: \
«в семь вечера» — 19:00, «в 9 утра» — 09:00. Нет даты или времени — null.
- end_date и end_time — конец события, если он назван. Иначе null.
- all_day — true для события на весь день или на несколько дней без времени. У задачи false.
- location — место события, если названо. Иначе null.
- repeat — daily, weekly или monthly, если событие повторяется. Тогда date — первый день \
повторений из таблицы: «каждый вторник» — ближайший вторник. repeat_until — последний день \
повторений («до конца года» — дата конца года из сведений выше). repeat_count — число повторений, \
только если оно названо словами «10 раз» и т. п. Заполняй что-то одно, второе — null. Не названо — \
оба null. Без повторов — none.
- reminders — только если пользователь просит напомнить: за сколько минут до события. \
«За час» — 60, «за день» — 1440. Не просит — пусто.
- reply — одно короткое предложение по-русски: что ты заполнил или что непонятно.

Если дана текущая карточка, пользователь её правит. Верни карточку целиком: меняй только то, \
о чём он просит, остальное перепиши из текущей карточки без изменений.\
"""


def _month_end(today: date) -> str:
    following = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (following - timedelta(days=1)).isoformat()


def _day_table(today: date) -> str:
    lines = []
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        note = {0: " — сегодня", 1: " — завтра", 2: " — послезавтра"}.get(offset, "")
        lines.append(f"{day.isoformat()} {WEEKDAYS[day.weekday()]}{note}")
    return "\n".join(lines)


def _people(ctx: Context) -> str:
    return "\n".join(
        f"- {person.name}" + (" (это пользователь)" if person.id == ctx.me.id else "")
        for person in ctx.people
    )


def _boards(ctx: Context) -> str:
    lines = []
    for board in ctx.boards:
        columns = ", ".join(column.name for column in board.columns)
        default = " (личная, по умолчанию)" if board.is_default else ""
        lines.append(f"- {board.name}{default}: колонки {columns}")
    return "\n".join(lines) or "- нет"


def _local(moment: datetime, ctx: Context) -> datetime:
    return moment.astimezone(ctx.zone)


def card_view(card: Card, ctx: Context) -> dict[str, Any]:
    """The card in the shape of ANSWER_SCHEMA, so the model can copy what it doesn't change."""
    names = {person.id: person.name for person in ctx.people}
    view: dict[str, Any] = {
        "kind": card.kind,
        "title": card.title,
        "description": card.description or "",
    }
    if isinstance(card, TaskCard):
        board = next((b for b in ctx.boards if b.id == card.board_id), None)
        column = board and next((c for c in board.columns if c.id == card.column_id), None)
        due = _local(card.due_at, ctx) if card.due_at else None
        due_day = due.date() if due else card.due_date
        view |= {
            "board": board.name if board else None,
            "column": column.name if column else None,
            "people": [names[i] for i in card.assignee_ids if i in names],
            "priority": card.priority,
            "checklist": list(card.checklist),
            "date": due_day.isoformat() if due_day else None,
            "time": due.strftime("%H:%M") if due else None,
        }
        return view
    start = _local(card.start_at, ctx) if card.start_at else None
    end = _local(card.end_at, ctx) if card.end_at else None
    recurrence = card.recurrence
    view |= {
        "people": [names[i] for i in card.participant_ids if i in names and i != ctx.me.id],
        "all_day": card.all_day,
        "date": str(start.date()) if start else (str(card.start_date) if card.start_date else None),
        "time": start.strftime("%H:%M") if start else None,
        "end_date": str(end.date()) if end else (str(card.end_date) if card.end_date else None),
        "end_time": end.strftime("%H:%M") if end else None,
        "location": card.location,
        "repeat": recurrence.freq if recurrence else "none",
        "repeat_until": str(recurrence.until) if recurrence and recurrence.until else None,
        "repeat_count": recurrence.count if recurrence else None,
        "reminders": list(card.reminder_minutes),
    }
    return view


def build_messages(
    ctx: Context, text: str, history: list[str], current: Card | None
) -> list[dict[str, str]]:
    """`history` is the user's earlier messages in this chat, oldest first, without `text`."""
    today = ctx.now.date()
    facts = [
        f"Сейчас {ctx.now:%Y-%m-%d %H:%M}, {WEEKDAYS[today.weekday()]}.",
        f"Таблица дней:\n{_day_table(today)}",
        f"Конец месяца — {_month_end(today)}, конец года — {today.year}-12-31.",
        f"Люди:\n{_people(ctx)}",
        f"Доски:\n{_boards(ctx)}",
    ]
    if current is not None:
        view = json.dumps(card_view(current, ctx), ensure_ascii=False)
        facts.append(f"Текущая карточка:\n{view}")
    if history:
        earlier = "\n".join(f"- {line}" for line in history[-MAX_HISTORY:])
        facts.append(f"Предыдущие сообщения пользователя:\n{earlier}")
    facts.append(f"Сообщение пользователя:\n{text}")
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(facts)},
    ]
