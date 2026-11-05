import { describe, expect, it } from "vitest";

import type { EventSummary } from "../../api/client";
import { makeDeadline, makeOccurrence } from "../tasks/testing";
import { validate, newDraft, type EventDraft } from "./EventForm";
import {
  eventDays,
  eventTime,
  eventWhen,
  gridInput,
  isShown,
  itemsOfDay,
  onDay,
  wallClock,
} from "./items";

const MOSCOW = "Europe/Moscow";
const TOKYO = "Asia/Tokyo";
const HONOLULU = "Pacific/Honolulu";
const COLORS = new Map([["work", "blue" as const]]);

const timed = (start_at: string, end_at: string) => makeOccurrence({ start_at, end_at });
const allDay = (start_date: string, end_date: string) =>
  makeOccurrence({ all_day: true, start_at: null, end_at: null, start_date, end_date });
const summary = (change: Partial<EventSummary> = {}): EventSummary => ({
  id: "e1",
  title: "Ужин вдвоём",
  all_day: false,
  start_at: "2026-11-06T16:00:00Z",
  start_date: null,
  is_recurring: false,
  next_occurrence_start: null,
  ...change,
});

describe("days of an event", () => {
  it("takes them from the zone of the reader", () => {
    const event = timed("2026-11-06T22:00:00Z", "2026-11-06T23:00:00Z");
    expect(eventDays(event, MOSCOW)).toEqual({ first: "2026-11-07", last: "2026-11-07" });
    expect(eventDays(event, HONOLULU)).toEqual({ first: "2026-11-06", last: "2026-11-06" });
  });

  it("doesn't let an event that ends at midnight reach the next day", () => {
    const event = timed("2026-11-06T18:00:00Z", "2026-11-06T21:00:00Z");
    expect(eventDays(event, MOSCOW)).toEqual({ first: "2026-11-06", last: "2026-11-06" });
  });

  it("counts both days of an event that crosses midnight", () => {
    const event = timed("2026-11-06T20:00:00Z", "2026-11-06T22:00:00Z");
    expect(eventDays(event, MOSCOW)).toEqual({ first: "2026-11-06", last: "2026-11-07" });
  });

  it("AC-09: leaves the dates of an all-day event alone in every zone", () => {
    const event = allDay("2026-11-06", "2026-11-06");
    for (const zone of [MOSCOW, TOKYO, HONOLULU]) {
      expect(eventDays(event, zone)).toEqual({ first: "2026-11-06", last: "2026-11-06" });
      expect(onDay(event, "2026-11-05", zone)).toBe(false);
      expect(onDay(event, "2026-11-06", zone)).toBe(true);
      expect(onDay(event, "2026-11-07", zone)).toBe(false);
    }
  });
});

describe("items of a day", () => {
  it("puts a deadline with a time on the local day", () => {
    const task = makeDeadline({ due_date: null, due_at: "2026-11-06T22:00:00Z" });
    expect(onDay(task, "2026-11-07", MOSCOW)).toBe(true);
    expect(onDay(task, "2026-11-06", HONOLULU)).toBe(true);
  });

  it("shows a many-day event on each of its days", () => {
    const trip = allDay("2026-11-28", "2026-11-29");
    expect(itemsOfDay([trip], "2026-11-29", MOSCOW).events).toEqual([trip]);
    expect(itemsOfDay([trip], "2026-11-30", MOSCOW).events).toEqual([]);
  });

  it("sorts events by start with all-day ones first and keeps tasks apart", () => {
    const late = makeOccurrence({
      event_id: "late",
      start_at: "2026-11-06T15:00:00Z",
      end_at: "2026-11-06T16:00:00Z",
    });
    const early = makeOccurrence({
      event_id: "early",
      start_at: "2026-11-06T07:00:00Z",
      end_at: "2026-11-06T08:00:00Z",
    });
    const birthday = { ...allDay("2026-11-06", "2026-11-06"), event_id: "birthday" };
    const task = makeDeadline();

    const { events, tasks } = itemsOfDay([late, task, early, birthday], "2026-11-06", MOSCOW);

    expect(events.map((event) => event.event_id)).toEqual(["birthday", "early", "late"]);
    expect(tasks).toEqual([task]);
  });
});

describe("time of an event as text", () => {
  it("is a pair of clock times in the zone of the reader", () => {
    const event = timed("2026-11-06T13:00:00Z", "2026-11-06T15:00:00Z");
    expect(eventTime(event, MOSCOW)).toBe("16:00 – 18:00");
  });

  it("names the days when the event doesn't fit in one", () => {
    const event = timed("2026-11-06T20:00:00Z", "2026-11-06T22:00:00Z");
    expect(eventTime(event, MOSCOW)).toBe("Пт, 6 ноября, 23:00 – Сб, 7 ноября, 01:00");
  });

  it("says all day, or the days of a longer one", () => {
    expect(eventTime(allDay("2026-11-06", "2026-11-06"), MOSCOW)).toBe("Весь день");
    expect(eventTime(allDay("2026-11-06", "2026-11-08"), MOSCOW)).toBe(
      "Пт, 6 ноября – Вс, 8 ноября",
    );
  });
});

describe("when an event is named in a list", () => {
  it("is its start in the zone of the reader", () => {
    expect(eventWhen(summary(), MOSCOW)).toBe("Пт, 6 ноября, 19:00");
  });

  it("is the next repeat of a series", () => {
    const series = summary({ is_recurring: true, next_occurrence_start: "2026-11-13T16:00:00Z" });
    expect(eventWhen(series, MOSCOW)).toBe("Пт, 13 ноября, 19:00");
  });

  it("is the start of a series that has no repeat left", () => {
    expect(eventWhen(summary({ is_recurring: true }), MOSCOW)).toBe("Пт, 6 ноября, 19:00");
  });

  it("is the day alone for an all-day event, and its next repeat is a day too", () => {
    const day = { all_day: true, start_at: null, start_date: "2026-11-06" };
    expect(eventWhen(summary(day), MOSCOW)).toBe("Пт, 6 ноября");
    const series = { ...day, is_recurring: true, next_occurrence_start: "2026-11-09" };
    expect(eventWhen(summary(series), MOSCOW)).toBe("Пн, 9 ноября");
  });
});

describe("filters", () => {
  const filters = { hiddenCategories: ["work"], tasksHidden: false };

  it("hides events of a hidden category only", () => {
    expect(isShown(makeOccurrence({ category_id: "work" }), filters)).toBe(false);
    expect(isShown(makeOccurrence({ category_id: "home" }), filters)).toBe(true);
  });

  it("keeps an event without a category: no switch could bring it back", () => {
    expect(isShown(makeOccurrence({ category_id: null }), filters)).toBe(true);
  });

  it("switches the task layer off as a whole", () => {
    expect(isShown(makeDeadline(), filters)).toBe(true);
    expect(isShown(makeDeadline(), { ...filters, tasksHidden: true })).toBe(false);
  });
});

describe("what FullCalendar gets", () => {
  it("is the wall clock of the profile zone, without an offset", () => {
    expect(wallClock("2026-11-06T13:05:00Z", MOSCOW)).toBe("2026-11-06T16:05:00");
    expect(wallClock("2026-11-06T13:05:00Z", TOKYO)).toBe("2026-11-06T22:05:00");
  });

  it("gives each repeat of a series its own id", () => {
    const first = makeOccurrence({ is_recurring: true });
    const second = makeOccurrence({
      is_recurring: true,
      occurrence_start: "2026-11-07T16:00:00Z",
      start_at: "2026-11-07T16:00:00Z",
      end_at: "2026-11-07T17:00:00Z",
    });
    const firstId = gridInput(first, MOSCOW, COLORS).id;
    const secondId = gridInput(second, MOSCOW, COLORS).id;
    expect(firstId).not.toBe(secondId);
    expect(firstId).toContain("e1");
  });

  it("makes the inclusive end of an all-day event exclusive", () => {
    const input = gridInput(allDay("2026-11-30", "2026-12-01"), MOSCOW, COLORS);
    expect(input).toMatchObject({ allDay: true, start: "2026-11-30", end: "2026-12-02" });
  });

  it("gives a timed event wall clock moments", () => {
    const input = gridInput(timed("2026-11-06T13:00:00Z", "2026-11-06T15:00:00Z"), MOSCOW, COLORS);
    expect(input).toMatchObject({
      allDay: false,
      start: "2026-11-06T16:00:00",
      end: "2026-11-06T18:00:00",
    });
  });

  it("puts a deadline in the all-day row, whatever its time", () => {
    const input = gridInput(
      makeDeadline({ due_date: null, due_at: "2026-11-06T22:00:00Z" }),
      MOSCOW,
      COLORS,
    );
    expect(input).toMatchObject({ allDay: true, start: "2026-11-07" });
    expect(input.end).toBeUndefined();
  });

  it("colours an event by the category of the reader", () => {
    const colored = gridInput(makeOccurrence({ category_id: "work" }), MOSCOW, COLORS);
    expect(colored.color).toBe("var(--cat-blue-fill)");
  });

  it("has a neutral colour without a category, or with one that isn't there any more", () => {
    const plain = gridInput(makeOccurrence({ category_id: null }), MOSCOW, COLORS);
    expect(plain.color).toBe("var(--surface-hover)");
    const stale = gridInput(makeOccurrence({ category_id: "gone" }), MOSCOW, COLORS);
    expect(stale.color).toBe("var(--surface-hover)");
  });

  it("puts events before deadlines, so that a full day folds the deadlines", () => {
    const event = gridInput(makeOccurrence(), MOSCOW, COLORS);
    const task = gridInput(makeDeadline(), MOSCOW, COLORS);
    expect(event.order).toBeLessThan(task.order);
  });
});

describe("the event form", () => {
  const draft = (change: Partial<EventDraft> = {}): EventDraft => ({
    ...newDraft("u1", "2026-11-06", "16:00"),
    title: "Встреча",
    ...change,
  });

  it("starts an hour long", () => {
    expect(newDraft("u1", "2026-11-06", "16:30")).toMatchObject({
      startTime: "16:30",
      endTime: "17:30",
      endDate: "2026-11-06",
      participantIds: ["u1"],
    });
  });

  it("stays within the day at the last hour", () => {
    expect(newDraft("u1", "2026-11-06", "23:30")).toMatchObject({
      endDate: "2026-11-06",
      endTime: "23:59",
    });
  });

  it("wants a title", () => {
    expect(validate(draft({ title: "   " })).title).toBe("Введите название");
  });

  it("wants the end after the start", () => {
    expect(validate(draft({ endTime: "16:00" })).end).toBe("Конец должен быть позже начала");
    expect(validate(draft({ endTime: "15:00" })).end).toBe("Конец должен быть позже начала");
    expect(validate(draft({ endDate: "2026-11-05" })).end).toBe(
      "Конец не может быть раньше начала",
    );
    expect(validate(draft({ endDate: "2026-11-07", endTime: "01:00" }))).toEqual({});
  });

  it("lets an all-day event end on the day it starts", () => {
    expect(validate(draft({ allDay: true, startTime: "", endTime: "" }))).toEqual({});
  });

  it("accepts a time the form didn't change, even when the end reads before the start", () => {
    // Across a clock change the server can hold an end that reads earlier than its start.
    const saved = draft({ endTime: "15:00" });
    expect(validate(saved, saved)).toEqual({});
    expect(validate(draft({ endTime: "15:00", title: "Другое" }), saved)).toEqual({});
  });

  it("checks the order again once the time is changed", () => {
    const saved = draft();
    expect(validate(draft({ endTime: "15:00" }), saved).end).toBe("Конец должен быть позже начала");
  });
});
