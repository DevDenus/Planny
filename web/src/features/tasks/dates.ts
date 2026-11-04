export type TaskGroup = "overdue" | "today" | "week" | "later" | "none";

type Deadline = { due_date: string | null; due_at: string | null };

export const TASK_GROUPS: { id: TaskGroup; title: string }[] = [
  { id: "overdue", title: "Просрочено" },
  { id: "today", title: "Сегодня" },
  { id: "week", title: "На этой неделе" },
  { id: "later", title: "Позже" },
  { id: "none", title: "Без срока" },
];

// Indexed by Date#getUTCDay(), so Sunday comes first.
const WEEKDAYS_SHORT = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
const MONTHS_SHORT = [
  "янв",
  "фев",
  "мар",
  "апр",
  "мая",
  "июн",
  "июл",
  "авг",
  "сен",
  "окт",
  "ноя",
  "дек",
];
const MONTHS_GENITIVE = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];

const DAY_MS = 24 * 60 * 60 * 1000;

interface ZonedFields {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

/** Calendar and clock fields of an instant (epoch ms) as seen in the zone. */
function zonedFields(instant: number, timeZone: string): ZonedFields {
  let formatter = formatters.get(timeZone);
  if (formatter === undefined) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      second: "numeric",
      hourCycle: "h23",
    });
    formatters.set(timeZone, formatter);
  }
  const parts = formatter.formatToParts(instant);
  const field = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((part) => part.type === type)?.value);
  return {
    year: field("year"),
    month: field("month"),
    day: field("day"),
    hour: field("hour"),
    minute: field("minute"),
    second: field("second"),
  };
}

/** Offset of the zone from UTC at the instant (epoch ms), in milliseconds. */
function offsetMs(instant: number, timeZone: string): number {
  const f = zonedFields(instant, timeZone);
  const wallAsUtc = Date.UTC(f.year, f.month - 1, f.day, f.hour, f.minute, f.second);
  return wallAsUtc - Math.floor(instant / 1000) * 1000;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function formatDay(year: number, month: number, day: number): string {
  return `${String(year).padStart(4, "0")}-${pad2(month)}-${pad2(day)}`;
}

function splitDay(day: string): [number, number, number] {
  const [year = 0, month = 0, date = 0] = day.split("-").map(Number);
  return [year, month, date];
}

/** Day of the week of a calendar day, 0 for Sunday. */
function weekday(day: string): number {
  const [year, month, date] = splitDay(day);
  return new Date(Date.UTC(year, month - 1, date)).getUTCDay();
}

/** The year is shown only when it differs from the year of today. */
function yearSuffix(day: string, today: string): string {
  const [year] = splitDay(day);
  const [todayYear] = splitDay(today);
  return year === todayYear ? "" : ` ${year}`;
}

function clockTime(moment: string, timeZone: string): string {
  const f = zonedFields(new Date(moment).getTime(), timeZone);
  return `${pad2(f.hour)}:${pad2(f.minute)}`;
}

/** Calendar day (YYYY-MM-DD) of a moment in the zone. */
export function localDate(moment: Date | string, timeZone: string): string {
  const f = zonedFields(new Date(moment).getTime(), timeZone);
  return formatDay(f.year, f.month, f.day);
}

/** Calendar arithmetic on YYYY-MM-DD; UTC is used only as a calendar, so no zone applies. */
export function addDays(day: string, days: number): string {
  const [year, month, date] = splitDay(day);
  const shifted = new Date(Date.UTC(year, month - 1, date + days));
  return formatDay(shifted.getUTCFullYear(), shifted.getUTCMonth() + 1, shifted.getUTCDate());
}

/** The Sunday of the week (Monday to Sunday) that contains the day. */
export function endOfWeek(day: string): string {
  return addDays(day, (7 - weekday(day)) % 7);
}

/** The deadline's calendar day in the zone. The backend allows only one of the two fields. */
function deadlineDay(task: Deadline, timeZone: string): string | null {
  return task.due_at === null ? task.due_date : localDate(task.due_at, timeZone);
}

export function taskGroup(task: Deadline, now: Date, timeZone: string): TaskGroup {
  const day = deadlineDay(task, timeZone);
  if (day === null) return "none";
  if (task.due_at !== null && new Date(task.due_at).getTime() < now.getTime()) return "overdue";
  const today = localDate(now, timeZone);
  if (day < today) return "overdue";
  if (day === today) return "today";
  return day <= endOfWeek(today) ? "week" : "later";
}

function relativeDayLabel(day: string, today: string): string | null {
  if (day === today) return "Сегодня";
  if (day === addDays(today, 1)) return "Завтра";
  if (day === addDays(today, -1)) return "Вчера";
  return null;
}

function shortDayLabel(day: string, today: string): string {
  const [, month, date] = splitDay(day);
  const weekdayName = WEEKDAYS_SHORT[weekday(day)];
  return `${weekdayName}, ${date} ${MONTHS_SHORT[month - 1]}${yearSuffix(day, today)}`;
}

export function formatDeadline(task: Deadline, now: Date, timeZone: string): string | null {
  const day = deadlineDay(task, timeZone);
  if (day === null) return null;
  const today = localDate(now, timeZone);
  const label = relativeDayLabel(day, today) ?? shortDayLabel(day, today);
  return task.due_at === null ? label : `${label}, ${clockTime(task.due_at, timeZone)}`;
}

export function formatMoment(moment: string, now: Date, timeZone: string): string {
  const day = localDate(moment, timeZone);
  const today = localDate(now, timeZone);
  const time = clockTime(moment, timeZone);
  if (day === today) return `сегодня, ${time}`;
  if (day === addDays(today, -1)) return `вчера, ${time}`;
  const [, month, date] = splitDay(day);
  return `${date} ${MONTHS_GENITIVE[month - 1]}${yearSuffix(day, today)}, ${time}`;
}

export function toLocalInput(
  moment: string | null,
  timeZone: string,
): { date: string; time: string } {
  if (moment === null) return { date: "", time: "" };
  return { date: localDate(moment, timeZone), time: clockTime(moment, timeZone) };
}

/**
 * Inverse of toLocalInput: the UTC instant of a wall-clock time in the zone, as ISO with Z.
 * The offset is taken at the instant itself, so DST changes are handled. A time repeated at a
 * fall-back change resolves to the earlier instant. A time skipped at a spring-forward change
 * resolves with the offset from before the change.
 */
export function fromLocalInput(date: string, time: string, timeZone: string): string {
  const [year, month, day] = splitDay(date);
  const [hour = 0, minute = 0] = time.split(":").map(Number);
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  // Offsets a day before and after cover a zone change close to the wall time.
  const before = offsetMs(wall - DAY_MS, timeZone);
  const after = offsetMs(wall + DAY_MS, timeZone);
  // An offset is valid when it holds at the instant it implies.
  const instants = [before, after]
    .filter((offset) => offsetMs(wall - offset, timeZone) === offset)
    .map((offset) => wall - offset);
  const instant = instants.length > 0 ? Math.min(...instants) : wall - before;
  return new Date(instant).toISOString().replace(/\.\d{3}Z$/, "Z");
}
