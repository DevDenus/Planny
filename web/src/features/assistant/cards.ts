import type { EventCard, TaskCard } from "../../api/client";
import { REMINDER_OPTIONS, NO_REMINDER, NO_REPEAT, reminderMinutes } from "../calendar/recurrence";
import { createBody as eventBody, validate as validateEvent } from "../calendar/EventForm";
import type { EventDraft } from "../calendar/EventForm";
import { toLocalInput } from "../tasks/dates";
import { createBody as taskBody, type Draft } from "../tasks/TaskDialog";

const DEFAULT_PRIORITY = "3";

/** A new task from the card. Without a board of its own it goes to the personal one. */
export function taskDraftFromCard(
  card: TaskCard,
  timeZone: string,
  personalBoardId: string,
): Draft {
  const due = card.due_at
    ? toLocalInput(card.due_at, timeZone)
    : { date: card.due_date ?? "", time: "" };
  return {
    title: card.title,
    boardId: card.board_id ?? personalBoardId,
    columnId: card.column_id ?? "",
    description: card.description ?? "",
    priority: String(card.priority ?? DEFAULT_PRIORITY),
    startDate: card.start_date ?? "",
    dueDate: due.date,
    dueTime: due.time,
    reminderDate: "",
    reminderTime: "",
    assigneeIds: card.assignee_ids ?? [],
    labelIds: [],
  };
}

/** The card laid over a saved task: what it doesn't hold stays as the task has it. */
export function taskProposedOnBase(card: TaskCard, base: Draft, timeZone: string): Draft {
  const proposed = taskDraftFromCard(card, timeZone, base.boardId);
  const sameBoard = proposed.boardId === base.boardId;
  return {
    ...proposed,
    columnId: card.column_id ?? (sameBoard ? base.columnId : ""),
    labelIds: sameBoard ? base.labelIds : [],
    reminderDate: base.reminderDate,
    reminderTime: base.reminderTime,
  };
}

export function cardFromTaskDraft(draft: Draft, checklist: string[], timeZone: string): TaskCard {
  const body = taskBody(draft, checklist, timeZone, "");
  return {
    kind: "task",
    title: body.title,
    description: body.description ?? null,
    board_id: body.board_id,
    column_id: body.column_id ?? null,
    priority: body.priority ?? 3,
    assignee_ids: body.assignee_ids ?? [],
    checklist,
    start_date: body.start_date ?? null,
    due_date: body.due_date ?? null,
    due_at: body.due_at ?? null,
  };
}

/** The reminder option closest to the asked minutes, the options being all the form can keep. */
function nearestReminder(minutes: number[]): string {
  const [first] = minutes;
  if (first === undefined) return NO_REMINDER;
  let best = NO_REMINDER;
  let distance = Infinity;
  for (const { value } of REMINDER_OPTIONS) {
    if (value === NO_REMINDER) continue;
    const gap = Math.abs(Number(value) - first);
    if (gap < distance) {
      best = value;
      distance = gap;
    }
  }
  return best;
}

/** The participants of a card leave out the current user, who is always in. */
export function eventDraftFromCard(card: EventCard, timeZone: string, meId: string): EventDraft {
  const start = toLocalInput(card.all_day ? null : (card.start_at ?? null), timeZone);
  const end = toLocalInput(card.all_day ? null : (card.end_at ?? null), timeZone);
  const { recurrence } = card;
  const others = (card.participant_ids ?? []).filter((id) => id !== meId);
  return {
    title: card.title,
    allDay: card.all_day,
    startDate: card.all_day ? (card.start_date ?? "") : start.date,
    startTime: start.time,
    endDate: card.all_day ? (card.end_date ?? card.start_date ?? "") : end.date,
    endTime: end.time,
    repeat: recurrence?.freq ?? NO_REPEAT,
    seriesEnd: recurrence?.until ? "until" : recurrence?.count ? "count" : "never",
    until: recurrence?.until ?? "",
    count: recurrence?.count ? String(recurrence.count) : "",
    participantIds: [meId, ...others],
    categoryId: "",
    reminder: nearestReminder(card.reminder_minutes ?? []),
    location: card.location ?? "",
    description: card.description ?? "",
  };
}

/** The card laid over a saved event: the category stays as the event has it. */
export function eventProposedOnBase(
  card: EventCard,
  base: EventDraft,
  timeZone: string,
  meId: string,
): EventDraft {
  return { ...eventDraftFromCard(card, timeZone, meId), categoryId: base.categoryId };
}

/** Null while the form can't be read as an event, a half-typed time has no instant. */
export function cardFromEventDraft(
  draft: EventDraft,
  timeZone: string,
  meId: string,
): EventCard | null {
  if (Object.keys(validateEvent(draft)).length > 0) return null;
  const body = eventBody(draft, timeZone, "");
  return {
    kind: "event",
    title: body.title,
    description: body.description ?? null,
    location: body.location ?? null,
    all_day: body.all_day ?? false,
    start_at: body.start_at ?? null,
    end_at: body.end_at ?? null,
    start_date: body.start_date ?? null,
    end_date: body.end_date ?? null,
    timezone: timeZone,
    participant_ids: draft.participantIds.filter((id) => id !== meId),
    recurrence: body.recurrence ?? null,
    reminder_minutes: reminderMinutes(draft.reminder),
  };
}
