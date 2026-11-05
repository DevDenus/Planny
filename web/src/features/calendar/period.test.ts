import { describe, expect, it } from "vitest";

import {
  dayHeading,
  dayNumber,
  dayTitle,
  mondayOf,
  monthGrid,
  periodTitle,
  sameMonth,
  shiftDay,
  viewRange,
} from "./period";

describe("viewRange", () => {
  it("covers the six weeks of the month grid for a month", () => {
    // November 2026 starts on a Sunday, so the grid begins on Monday 26 October.
    expect(viewRange("month", "2026-11-15")).toEqual({ first: "2026-10-26", end: "2026-12-07" });
  });

  it("covers the Monday to Sunday of the week", () => {
    expect(viewRange("week", "2026-11-06")).toEqual({ first: "2026-11-02", end: "2026-11-09" });
  });

  it("covers the Monday before a Sunday", () => {
    expect(viewRange("week", "2026-11-08")).toEqual({ first: "2026-11-02", end: "2026-11-09" });
  });

  it("covers only the day itself", () => {
    expect(viewRange("day", "2026-11-06")).toEqual({ first: "2026-11-06", end: "2026-11-07" });
  });

  it("ends the day at the start of the next year", () => {
    expect(viewRange("day", "2026-12-31")).toEqual({ first: "2026-12-31", end: "2027-01-01" });
  });
});

describe("mondayOf", () => {
  it("returns a Monday unchanged", () => {
    expect(mondayOf("2026-11-02")).toBe("2026-11-02");
  });

  it("returns the Monday of the same week for midweek and Saturday", () => {
    expect(mondayOf("2026-11-04")).toBe("2026-11-02");
    expect(mondayOf("2026-11-07")).toBe("2026-11-02");
  });

  it("returns the Monday before a Sunday, not the Monday after it", () => {
    // 8 Nov 2026 is a Sunday: its week starts six days earlier.
    expect(mondayOf("2026-11-08")).toBe("2026-11-02");
  });

  it("crosses a month end and a year end", () => {
    // 1 Dec 2026 is a Tuesday.
    expect(mondayOf("2026-12-01")).toBe("2026-11-30");
    // 1 Jan 2027 is a Friday.
    expect(mondayOf("2027-01-01")).toBe("2026-12-28");
  });
});

describe("monthGrid", () => {
  it("has 42 days", () => {
    expect(monthGrid("2026-06-10")).toHaveLength(42);
  });

  it("starts on the 1st when the month starts on a Monday", () => {
    // 1 June 2026 is a Monday.
    const grid = monthGrid("2026-06-10");
    expect(grid[0]).toBe("2026-06-01");
    expect(grid[41]).toBe("2026-07-12");
  });

  it("starts on the Monday before the 1st when the month starts on a Sunday", () => {
    // 1 November 2026 is a Sunday.
    const grid = monthGrid("2026-11-15");
    expect(grid[0]).toBe("2026-10-26");
    expect(grid[41]).toBe("2026-12-06");
  });

  it("holds the 29th of a leap February", () => {
    // 1 February 2028 is a Tuesday.
    const grid = monthGrid("2028-02-10");
    expect(grid[0]).toBe("2028-01-31");
    expect(grid).toContain("2028-02-29");
    expect(grid[41]).toBe("2028-03-12");
  });

  it("is the same grid for any day of the month", () => {
    expect(monthGrid("2026-11-30")).toEqual(monthGrid("2026-11-01"));
  });
});

describe("shiftDay", () => {
  it("moves by a week or by a day", () => {
    expect(shiftDay("week", "2026-11-06", 1)).toBe("2026-11-13");
    expect(shiftDay("week", "2026-11-06", -1)).toBe("2026-10-30");
    expect(shiftDay("day", "2026-11-06", 1)).toBe("2026-11-07");
    expect(shiftDay("day", "2026-11-06", -1)).toBe("2026-11-05");
  });

  it("moves a month to the same number of the next or previous month", () => {
    expect(shiftDay("month", "2026-11-06", 1)).toBe("2026-12-06");
    expect(shiftDay("month", "2026-11-06", -1)).toBe("2026-10-06");
  });

  it("crosses a year end in both directions", () => {
    expect(shiftDay("month", "2026-12-15", 1)).toBe("2027-01-15");
    expect(shiftDay("month", "2027-01-15", -1)).toBe("2026-12-15");
    expect(shiftDay("week", "2026-12-31", 1)).toBe("2027-01-07");
    expect(shiftDay("week", "2027-01-03", -1)).toBe("2026-12-27");
    expect(shiftDay("day", "2026-12-31", 1)).toBe("2027-01-01");
    expect(shiftDay("day", "2027-01-01", -1)).toBe("2026-12-31");
  });

  it("clamps to the last day of a shorter month", () => {
    expect(shiftDay("month", "2027-01-31", 1)).toBe("2027-02-28");
    expect(shiftDay("month", "2028-01-31", 1)).toBe("2028-02-29");
    expect(shiftDay("month", "2026-10-31", 1)).toBe("2026-11-30");
    expect(shiftDay("month", "2027-03-31", -1)).toBe("2027-02-28");
  });
});

describe("periodTitle", () => {
  it("names a month in the nominative with the year, for any day of it", () => {
    expect(periodTitle("month", "2026-11-01")).toBe("Ноябрь 2026");
    expect(periodTitle("month", "2026-11-30")).toBe("Ноябрь 2026");
    expect(periodTitle("month", "2026-06-10")).toBe("Июнь 2026");
  });

  it("gives a week inside one month", () => {
    // The week of Monday 2 November runs to Sunday 8 November.
    expect(periodTitle("week", "2026-11-04")).toBe("2 – 8 ноября 2026");
    expect(periodTitle("week", "2026-11-10")).toBe("9 – 15 ноября 2026");
  });

  it("gives a week across two months", () => {
    // 2 December 2026 is a Wednesday, so its week starts on Monday 30 November.
    expect(periodTitle("week", "2026-12-02")).toBe("30 ноября – 6 декабря 2026");
  });

  it("gives a week across two years", () => {
    // 1 January 2026 is a Thursday, so its week starts on Monday 29 December 2025.
    expect(periodTitle("week", "2026-01-01")).toBe("29 декабря 2025 – 4 января 2026");
  });

  it("gives a day with its short weekday and the genitive month", () => {
    expect(periodTitle("day", "2026-11-06")).toBe("Пт, 6 ноября 2026");
  });
});

describe("dayTitle", () => {
  it("gives the weekday, the day and the genitive month without the year", () => {
    expect(dayTitle("2026-11-06")).toBe("Пт, 6 ноября");
  });

  it("uses the genitive form of every month, including June", () => {
    // 1 June 2026 is a Monday.
    expect(dayTitle("2026-06-01")).toBe("Пн, 1 июня");
  });

  it("names Sunday", () => {
    expect(dayTitle("2026-11-08")).toBe("Вс, 8 ноября");
  });
});

describe("sameMonth", () => {
  it("is true for two days of the same month", () => {
    expect(sameMonth("2026-11-01", "2026-11-30")).toBe(true);
  });

  it("is false across a month boundary, even inside one week", () => {
    expect(sameMonth("2026-10-31", "2026-11-01")).toBe(false);
  });

  it("is false for the same month in another year", () => {
    expect(sameMonth("2026-11-06", "2027-11-06")).toBe(false);
  });
});

describe("dayNumber", () => {
  it("returns the number of the day in its month", () => {
    expect(dayNumber("2026-11-01")).toBe(1);
    expect(dayNumber("2026-11-06")).toBe(6);
    expect(dayNumber("2028-02-29")).toBe(29);
  });
});

describe("dayHeading", () => {
  it("gives the weekday and the short date of a grid column", () => {
    expect(dayHeading("2026-11-02")).toEqual({ weekday: "Пн", date: "2 ноя" });
    expect(dayHeading("2026-05-10")).toEqual({ weekday: "Вс", date: "10 мая" });
  });
});
