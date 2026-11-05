import type {
  CalendarItem,
  Category,
  CategoryColor,
  EventOccurrence,
  TaskDeadline,
} from "../../api/client";
import { addDays, clockTime, deadlineDay, localDate } from "../tasks/dates";
import type { CalendarFilters } from "./filters";
import { dayTitle } from "./period";

export type TimedEvent = Pick<
  EventOccurrence,
  "all_day" | "start_at" | "end_at" | "start_date" | "end_date"
>;

export function colorsOf(categories: Category[] | undefined): Map<string, CategoryColor> {
  return new Map(categories?.map((category) => [category.id, category.color]));
}

export function isShown(item: CalendarItem, filters: CalendarFilters): boolean {
  if (item.type === "task") return !filters.tasksHidden;
  return item.category_id === null || !filters.hiddenCategories.includes(item.category_id);
}

/** The days an event touches for the reader. An event that ends at midnight stays on its day. */
export function eventDays(event: TimedEvent, timeZone: string): { first: string; last: string } {
  if (event.all_day) return { first: event.start_date ?? "", last: event.end_date ?? "" };
  const lastMoment = new Date(new Date(event.end_at ?? 0).getTime() - 1);
  return {
    first: localDate(event.start_at ?? "", timeZone),
    last: localDate(lastMoment, timeZone),
  };
}

export function onDay(item: CalendarItem, day: string, timeZone: string): boolean {
  if (item.type === "task") return deadlineDay(item, timeZone) === day;
  const { first, last } = eventDays(item, timeZone);
  return first <= day && day <= last;
}

export function itemsOfDay(
  items: CalendarItem[],
  day: string,
  timeZone: string,
): { events: EventOccurrence[]; tasks: TaskDeadline[] } {
  const present = items.filter((item) => onDay(item, day, timeZone));
  return {
    events: present
      .filter((item) => item.type === "event")
      .sort((left, right) => startKey(left).localeCompare(startKey(right))),
    tasks: present.filter((item) => item.type === "task"),
  };
}

/** All-day events go first: as a date it sorts before any moment of the same day. */
function startKey(event: EventOccurrence): string {
  return event.start_date ?? event.start_at ?? "";
}

/** "16:00 – 18:00", or with the days when the event doesn't fit in one. */
export function eventTime(event: TimedEvent, timeZone: string): string {
  const { first, last } = eventDays(event, timeZone);
  if (event.all_day) {
    return first === last ? "Весь день" : `${dayTitle(first)} – ${dayTitle(last)}`;
  }
  const start = clockTime(event.start_at ?? "", timeZone);
  const end = clockTime(event.end_at ?? "", timeZone);
  if (first === last) return `${start} – ${end}`;
  return `${dayTitle(first)}, ${start} – ${dayTitle(last)}, ${end}`;
}

/**
 * FullCalendar runs in UTC and gets the wall clock of the user: it never sees a real instant, so
 * the zone from the profile holds whatever the zone of the browser is.
 */
export function wallClock(moment: Date | string, timeZone: string): string {
  return `${localDate(moment, timeZone)}T${clockTime(new Date(moment).toISOString(), timeZone)}:00`;
}

export type GridInput = {
  id: string;
  title: string;
  start: string;
  end?: string;
  allDay: boolean;
  /** Events go before deadlines: in a full day of a month it is the deadlines that fold. */
  order: number;
  color: string;
  contrastColor: string;
  extendedProps: { item: CalendarItem };
};

function fillOf(event: EventOccurrence, colors: Map<string, CategoryColor>): string {
  const color = event.category_id === null ? undefined : colors.get(event.category_id);
  return color ? `var(--cat-${color}-fill)` : "var(--surface-hover)";
}

export function gridInput(
  item: CalendarItem,
  timeZone: string,
  colors: Map<string, CategoryColor>,
): GridInput {
  if (item.type === "task") {
    return {
      id: `task-${item.task_id}`,
      title: item.title,
      start: deadlineDay(item, timeZone) ?? "",
      allDay: true,
      order: 1,
      color: "transparent",
      contrastColor: "var(--text-secondary)",
      extendedProps: { item },
    };
  }
  const base = {
    id: `event-${item.event_id}`,
    title: item.title,
    order: 0,
    color: fillOf(item, colors),
    contrastColor: "var(--text-primary)",
    extendedProps: { item },
  };
  if (item.all_day) {
    return {
      ...base,
      allDay: true,
      start: item.start_date ?? "",
      // The end of a range is not in it for FullCalendar, and inclusive for the API.
      end: addDays(item.end_date ?? "", 1),
    };
  }
  return {
    ...base,
    allDay: false,
    start: wallClock(item.start_at ?? "", timeZone),
    end: wallClock(item.end_at ?? "", timeZone),
  };
}
