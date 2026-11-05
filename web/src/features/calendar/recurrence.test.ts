import { describe, expect, it } from "vitest";

import { makeEvent } from "../tasks/testing";
import { occurrenceOf, recurrenceText, reminderMinutes, reminderValue } from "./recurrence";

const series = { freq: "monthly", until: null, count: null } as const;

describe("recurrenceText", () => {
  it("names the step of a series without an end", () => {
    expect(recurrenceText(series)).toBe("Каждый месяц");
    expect(recurrenceText({ ...series, freq: "daily" })).toBe("Каждый день");
    expect(recurrenceText({ ...series, freq: "weekly" })).toBe("Каждую неделю");
  });

  it("adds the last day with its year", () => {
    expect(recurrenceText({ ...series, until: "2027-12-31" })).toBe(
      "Каждый месяц, до Пт, 31 декабря 2027",
    );
  });

  it("declines the number of repeats", () => {
    expect(recurrenceText({ ...series, count: 1 })).toBe("Каждый месяц, 1 раз");
    expect(recurrenceText({ ...series, count: 4 })).toBe("Каждый месяц, 4 раза");
    expect(recurrenceText({ ...series, count: 12 })).toBe("Каждый месяц, 12 раз");
  });
});

describe("the reminder of the form", () => {
  it("reads the first value of the list, and no value as none", () => {
    expect(reminderValue([])).toBe("");
    expect(reminderValue([60, 15])).toBe("60");
  });

  it("writes a list back", () => {
    expect(reminderMinutes("")).toEqual([]);
    expect(reminderMinutes("0")).toEqual([0]);
    expect(reminderMinutes("1440")).toEqual([1440]);
  });
});

describe("occurrenceOf", () => {
  const timed = makeEvent({ recurrence: series });

  it("moves an event with a time and keeps its length", () => {
    expect(occurrenceOf(timed, "2027-03-06T16:00:00Z")).toMatchObject({
      start_at: "2027-03-06T16:00:00Z",
      end_at: "2027-03-06T17:00:00.000Z",
    });
  });

  it("moves the dates of an all-day event and keeps the number of days", () => {
    const allDay = makeEvent({
      recurrence: series,
      all_day: true,
      start_at: null,
      end_at: null,
      start_date: "2026-11-06",
      end_date: "2026-11-07",
    });

    expect(occurrenceOf(allDay, "2026-12-06")).toMatchObject({
      start_date: "2026-12-06",
      end_date: "2026-12-07",
    });
  });

  it("leaves the first occurrence without a start, or with one that isn't a date", () => {
    expect(occurrenceOf(timed, undefined)).toBe(timed);
    expect(occurrenceOf(timed, "вчера")).toBe(timed);
  });

  it("leaves a one-off event as it is", () => {
    const single = makeEvent();

    expect(occurrenceOf(single, "2027-03-06T16:00:00Z")).toBe(single);
  });
});
