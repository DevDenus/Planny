import { addDays, MONTHS_SHORT } from "../tasks/dates";

export type CalendarView = "month" | "week" | "day";

const MONTHS_NOMINATIVE = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
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
// Indexed by Date#getUTCDay(), so Sunday comes first.
const WEEKDAYS_SHORT = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];

const GRID_DAYS = 42;
const WEEK_DAYS = 7;

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

/** Days in a month given as 1 to 12. Day 0 of the next month is the last day of this one. */
function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function firstOfMonth(day: string): string {
  const [year, month] = splitDay(day);
  return formatDay(year, month, 1);
}

/** The Monday of the week (Monday to Sunday) that contains the day. */
export function mondayOf(day: string): string {
  // Counted from Monday, so Sunday is six days after the Monday before it.
  return addDays(day, -((weekday(day) + 6) % 7));
}

/** Days a view shows. `end` is the day after the last one, as in the half-open periods of the API. */
export function viewRange(view: CalendarView, day: string): { first: string; end: string } {
  if (view === "month") {
    const first = mondayOf(firstOfMonth(day));
    return { first, end: addDays(first, GRID_DAYS) };
  }
  if (view === "week") {
    const first = mondayOf(day);
    return { first, end: addDays(first, WEEK_DAYS) };
  }
  return { first: day, end: addDays(day, 1) };
}

/** The 42 days of a month grid: the Monday of the week of the 1st, six full weeks, always. */
export function monthGrid(day: string): string[] {
  const first = mondayOf(firstOfMonth(day));
  return Array.from({ length: GRID_DAYS }, (_, index) => addDays(first, index));
}

/**
 * The day the arrows lead to: the same number in the next or previous month (clamped to the last
 * day of a shorter month, so 31 Jan + 1 month is 28 Feb), or +-7 days, or +-1 day. `direction` is
 * 1 or -1.
 */
export function shiftDay(view: CalendarView, day: string, direction: 1 | -1): string {
  if (view === "month") {
    const [year, month, date] = splitDay(day);
    // Months are counted from year 0, so the shift carries over a year end in both directions.
    const index = year * 12 + (month - 1) + direction;
    const targetYear = Math.floor(index / 12);
    const targetMonth = index - targetYear * 12 + 1;
    const lastDate = daysInMonth(targetYear, targetMonth);
    return formatDay(targetYear, targetMonth, Math.min(date, lastDate));
  }
  return addDays(day, (view === "week" ? WEEK_DAYS : 1) * direction);
}

/** "Пт, 6 ноября": the heading of the day panel. */
export function dayTitle(day: string): string {
  const [, month, date] = splitDay(day);
  return `${WEEKDAYS_SHORT[weekday(day)]}, ${date} ${MONTHS_GENITIVE[month - 1]}`;
}

function weekTitle(day: string): string {
  const first = mondayOf(day);
  const last = addDays(first, WEEK_DAYS - 1);
  const [firstYear, firstMonth, firstDate] = splitDay(first);
  const [lastYear, lastMonth, lastDate] = splitDay(last);
  // The start names its month and year only when they differ from the end's.
  const startMonth = firstMonth === lastMonth ? "" : ` ${MONTHS_GENITIVE[firstMonth - 1]}`;
  const startYear = firstYear === lastYear ? "" : ` ${firstYear}`;
  const end = `${lastDate} ${MONTHS_GENITIVE[lastMonth - 1]} ${lastYear}`;
  return `${firstDate}${startMonth}${startYear} – ${end}`;
}

/** The heading of the period. */
export function periodTitle(view: CalendarView, day: string): string {
  if (view === "month") {
    const [year, month] = splitDay(day);
    return `${MONTHS_NOMINATIVE[month - 1]} ${year}`;
  }
  if (view === "week") return weekTitle(day);
  const [year] = splitDay(day);
  return `${dayTitle(day)} ${year}`;
}

export function sameMonth(left: string, right: string): boolean {
  const [leftYear, leftMonth] = splitDay(left);
  const [rightYear, rightMonth] = splitDay(right);
  return leftYear === rightYear && leftMonth === rightMonth;
}

/** 1 to 31, the number of the day. */
export function dayNumber(day: string): number {
  const [, , date] = splitDay(day);
  return date;
}

/** The heading of a column of the grid: "Пн" and "2 ноя". */
export function dayHeading(day: string): { weekday: string; date: string } {
  const [, month = 1, date = 1] = day.split("-").map(Number);
  return { weekday: dayTitle(day).slice(0, 2), date: `${date} ${MONTHS_SHORT[month - 1]}` };
}
