import type { CalendarEvent } from "../../api/client";
import { addDays } from "../tasks/dates";
import { pluralize } from "../tasks/labels";
import type { TimedEvent } from "./items";
import { dayTitle } from "./period";

type Recurrence = NonNullable<CalendarEvent["recurrence"]>;
export type RecurrenceFreq = Recurrence["freq"];
export type SeriesEnd = "never" | "until" | "count";

export const MAX_SERIES_COUNT = 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

const FREQ_LABELS: Record<RecurrenceFreq, string> = {
  daily: "Каждый день",
  weekly: "Каждую неделю",
  monthly: "Каждый месяц",
};

export const NO_REPEAT = "";
export const REPEAT_OPTIONS = [
  { value: NO_REPEAT, label: "Не повторять" },
  ...Object.entries(FREQ_LABELS).map(([value, label]) => ({ value, label })),
];

export const SERIES_END_OPTIONS: { value: SeriesEnd; label: string }[] = [
  { value: "never", label: "Никогда" },
  { value: "until", label: "До даты" },
  { value: "count", label: "N раз" },
];

export const NO_REMINDER = "";
export const REMINDER_OPTIONS = [
  { value: NO_REMINDER, label: "Нет" },
  { value: "0", label: "В момент начала" },
  { value: "5", label: "За 5 минут" },
  { value: "15", label: "За 15 минут" },
  { value: "30", label: "За 30 минут" },
  { value: "60", label: "За 1 час" },
  { value: "1440", label: "За 1 день" },
];

/** The API keeps a list, and the first version of the app needs one value of it. */
export function reminderValue(minutes: number[]): string {
  const [first] = minutes;
  return first === undefined ? NO_REMINDER : String(first);
}

export function reminderMinutes(value: string): number[] {
  return value === NO_REMINDER ? [] : [Number(value)];
}

export function recurrenceText({ freq, until, count }: Recurrence): string {
  const rule = FREQ_LABELS[freq];
  if (until !== null) return `${rule}, до ${dayTitle(until)} ${until.slice(0, 4)}`;
  if (count !== null) return `${rule}, ${count} ${pluralize(count, "раз", "раза", "раз")}`;
  return rule;
}

/** The dates of one repeat. A start that doesn't read as a date leaves the first one. */
export function occurrenceOf(event: CalendarEvent, start: string | undefined): TimedEvent {
  const startMs = Date.parse(start ?? "");
  if (start === undefined || event.recurrence === null || Number.isNaN(startMs)) return event;
  if (event.all_day) {
    const length = Date.parse(event.end_date ?? "") - Date.parse(event.start_date ?? "");
    return { ...event, start_date: start, end_date: addDays(start, length / DAY_MS) };
  }
  const length = Date.parse(event.end_at ?? "") - Date.parse(event.start_at ?? "");
  return { ...event, start_at: start, end_at: new Date(startMs + length).toISOString() };
}
