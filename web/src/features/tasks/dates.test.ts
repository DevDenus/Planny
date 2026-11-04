import { describe, expect, it } from "vitest";

import {
  addDays,
  endOfWeek,
  formatDeadline,
  formatMoment,
  fromLocalInput,
  localDate,
  TASK_GROUPS,
  taskGroup,
  toLocalInput,
} from "./dates";

const MOSCOW = "Europe/Moscow"; // UTC+3 all year
const VLADIVOSTOK = "Asia/Vladivostok"; // UTC+10 all year
const NEW_YORK = "America/New_York"; // UTC-4 in summer, UTC-5 in winter

// Wednesday 4 Nov 2026, 12:00 UTC: 15:00 in Moscow, 22:00 in Vladivostok, 07:00 in New York.
const NOW = new Date("2026-11-04T12:00:00Z");

const onDay = (day: string) => ({ due_date: day, due_at: null });
const atMoment = (moment: string) => ({ due_date: null, due_at: moment });

describe("localDate", () => {
  it("returns the calendar day of the moment in the zone", () => {
    // 23:30 UTC is already the next day in Moscow and Vladivostok.
    expect(localDate("2026-11-04T23:30:00Z", MOSCOW)).toBe("2026-11-05");
    expect(localDate(new Date("2026-11-04T23:30:00Z"), VLADIVOSTOK)).toBe("2026-11-05");
  });

  it("follows the zone's offset at that moment", () => {
    // New York is UTC-4 in July, so 03:30 UTC is still the previous evening.
    expect(localDate("2026-07-15T03:30:00Z", NEW_YORK)).toBe("2026-07-14");
    // In January it is UTC-5.
    expect(localDate("2026-01-15T03:30:00Z", NEW_YORK)).toBe("2026-01-14");
  });
});

describe("addDays", () => {
  it("moves within a month", () => {
    expect(addDays("2026-11-04", 1)).toBe("2026-11-05");
    expect(addDays("2026-11-04", -4)).toBe("2026-10-31");
  });

  it("returns the same day for zero", () => {
    expect(addDays("2026-11-04", 0)).toBe("2026-11-04");
  });

  it("crosses a year end in both directions", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2027-01-01", -1)).toBe("2026-12-31");
    expect(addDays("2026-12-31", 365)).toBe("2027-12-31");
  });

  it("crosses month ends, including February of a leap year", () => {
    expect(addDays("2026-01-31", 1)).toBe("2026-02-01");
    expect(addDays("2026-02-28", 1)).toBe("2026-03-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
  });
});

describe("endOfWeek", () => {
  it("returns the Sunday of the week that starts on a Monday", () => {
    expect(endOfWeek("2026-11-02")).toBe("2026-11-08");
  });

  it("returns a Sunday unchanged", () => {
    expect(endOfWeek("2026-11-08")).toBe("2026-11-08");
  });

  it("returns the Sunday of the same week for midweek and Saturday", () => {
    expect(endOfWeek("2026-11-04")).toBe("2026-11-08");
    expect(endOfWeek("2026-11-07")).toBe("2026-11-08");
  });

  it("crosses the year end", () => {
    // 31 Dec 2026 is a Thursday.
    expect(endOfWeek("2026-12-31")).toBe("2027-01-03");
  });
});

describe("TASK_GROUPS", () => {
  it("lists the groups in display order with Russian titles", () => {
    expect(TASK_GROUPS).toEqual([
      { id: "overdue", title: "Просрочено" },
      { id: "today", title: "Сегодня" },
      { id: "week", title: "На этой неделе" },
      { id: "later", title: "Позже" },
      { id: "none", title: "Без срока" },
    ]);
  });
});

describe("taskGroup", () => {
  it("returns none without a deadline", () => {
    expect(taskGroup({ due_date: null, due_at: null }, NOW, MOSCOW)).toBe("none");
  });

  it("returns overdue for a due_at before now, even on the same day", () => {
    // 11:59 UTC is 14:59 in Moscow: today, but already past.
    expect(taskGroup(atMoment("2026-11-04T11:59:00Z"), NOW, MOSCOW)).toBe("overdue");
  });

  it("returns overdue for a due_date before today", () => {
    expect(taskGroup(onDay("2026-11-03"), NOW, MOSCOW)).toBe("overdue");
  });

  it("returns overdue for a due_at on an earlier day", () => {
    // 20:00 UTC on 3 Nov is 23:00 on 3 Nov in Moscow.
    expect(taskGroup(atMoment("2026-11-03T20:00:00Z"), NOW, MOSCOW)).toBe("overdue");
  });

  it("returns today for a due_date on today", () => {
    expect(taskGroup(onDay("2026-11-04"), NOW, MOSCOW)).toBe("today");
  });

  it("returns today for a due_at later today", () => {
    // 13:00 UTC is 16:00 in Moscow.
    expect(taskGroup(atMoment("2026-11-04T13:00:00Z"), NOW, MOSCOW)).toBe("today");
  });

  it("takes the calendar day in the zone, not the UTC day", () => {
    // 23:30 UTC on 4 Nov is 02:30 on 5 Nov in Moscow: tomorrow, not today.
    expect(taskGroup(atMoment("2026-11-04T23:30:00Z"), NOW, MOSCOW)).toBe("week");
  });

  it("returns week up to and including the Sunday of this week", () => {
    expect(taskGroup(onDay("2026-11-05"), NOW, MOSCOW)).toBe("week");
    expect(taskGroup(onDay("2026-11-08"), NOW, MOSCOW)).toBe("week");
  });

  it("returns later after this week", () => {
    expect(taskGroup(onDay("2026-11-09"), NOW, MOSCOW)).toBe("later");
    expect(taskGroup(atMoment("2026-11-20T09:00:00Z"), NOW, MOSCOW)).toBe("later");
  });

  it("compares a due_date with each zone's own today", () => {
    // 18:00 UTC is still 4 Nov in Moscow and New York, but already 5 Nov in Vladivostok.
    const later = new Date("2026-11-04T18:00:00Z");
    const task = onDay("2026-11-04");
    expect(taskGroup(task, later, MOSCOW)).toBe("today");
    expect(taskGroup(task, later, NEW_YORK)).toBe("today");
    expect(taskGroup(task, later, VLADIVOSTOK)).toBe("overdue");
  });
});

describe("formatDeadline", () => {
  it("returns null without a deadline", () => {
    expect(formatDeadline({ due_date: null, due_at: null }, NOW, MOSCOW)).toBeNull();
  });

  it("uses relative words for today, tomorrow and yesterday", () => {
    expect(formatDeadline(onDay("2026-11-04"), NOW, MOSCOW)).toBe("Сегодня");
    expect(formatDeadline(onDay("2026-11-05"), NOW, MOSCOW)).toBe("Завтра");
    expect(formatDeadline(onDay("2026-11-03"), NOW, MOSCOW)).toBe("Вчера");
  });

  it("adds the time in 24-hour format for a due_at", () => {
    // 14:00 UTC is 17:00 in Moscow.
    expect(formatDeadline(atMoment("2026-11-04T14:00:00Z"), NOW, MOSCOW)).toBe("Сегодня, 17:00");
    // 06:05 UTC is 09:05 in Moscow.
    expect(formatDeadline(atMoment("2026-11-05T06:05:00Z"), NOW, MOSCOW)).toBe("Завтра, 09:05");
    expect(formatDeadline(atMoment("2026-11-03T06:05:00Z"), NOW, MOSCOW)).toBe("Вчера, 09:05");
  });

  it("uses the time in the zone and shows midnight as 00:00", () => {
    // 14:00 UTC is 09:00 in New York, and 00:00 on 5 Nov in Vladivostok.
    expect(formatDeadline(atMoment("2026-11-04T14:00:00Z"), NOW, NEW_YORK)).toBe("Сегодня, 09:00");
    expect(formatDeadline(atMoment("2026-11-04T14:00:00Z"), NOW, VLADIVOSTOK)).toBe(
      "Завтра, 00:00",
    );
  });

  it("uses the short weekday and date on other days", () => {
    expect(formatDeadline(onDay("2026-11-06"), NOW, MOSCOW)).toBe("Пт, 6 ноя");
    expect(formatDeadline(atMoment("2026-11-06T14:00:00Z"), NOW, MOSCOW)).toBe("Пт, 6 ноя, 17:00");
  });

  it("adds the year only when it differs from the current year", () => {
    // 6 Nov 2027 is a Saturday.
    expect(formatDeadline(onDay("2027-11-06"), NOW, MOSCOW)).toBe("Сб, 6 ноя 2027");
    expect(formatDeadline(atMoment("2027-11-06T14:00:00Z"), NOW, MOSCOW)).toBe(
      "Сб, 6 ноя 2027, 17:00",
    );
  });

  it("never shifts a due_date to another day in any zone", () => {
    for (const zone of [MOSCOW, VLADIVOSTOK, NEW_YORK]) {
      expect(formatDeadline(onDay("2026-11-06"), NOW, zone)).toBe("Пт, 6 ноя");
    }
  });

  it("gives relative words from the zone's today for a due_date", () => {
    const later = new Date("2026-11-04T18:00:00Z");
    // 21:00 on 4 Nov in Moscow, 04:00 on 5 Nov in Vladivostok.
    expect(formatDeadline(onDay("2026-11-05"), later, MOSCOW)).toBe("Завтра");
    expect(formatDeadline(onDay("2026-11-05"), later, VLADIVOSTOK)).toBe("Сегодня");
  });
});

describe("formatMoment", () => {
  it("uses сегодня and вчера with the time", () => {
    expect(formatMoment("2026-11-04T14:00:00Z", NOW, MOSCOW)).toBe("сегодня, 17:00");
    expect(formatMoment("2026-11-03T06:05:00Z", NOW, MOSCOW)).toBe("вчера, 09:05");
  });

  it("uses the day and the genitive month otherwise", () => {
    expect(formatMoment("2026-11-06T14:00:00Z", NOW, MOSCOW)).toBe("6 ноября, 17:00");
    // Tomorrow has no special word here.
    expect(formatMoment("2026-11-05T09:05:00Z", NOW, MOSCOW)).toBe("5 ноября, 12:05");
  });

  it("adds the year when it differs from the current year", () => {
    expect(formatMoment("2025-11-06T14:00:00Z", NOW, MOSCOW)).toBe("6 ноября 2025, 17:00");
  });

  it("uses the zone's day and shows midnight as 00:00", () => {
    // 21:00 UTC on 3 Nov is 00:00 on 4 Nov in Moscow.
    expect(formatMoment("2026-11-03T21:00:00Z", NOW, MOSCOW)).toBe("сегодня, 00:00");
  });
});

describe("toLocalInput", () => {
  it("returns empty strings for no moment", () => {
    expect(toLocalInput(null, MOSCOW)).toEqual({ date: "", time: "" });
  });

  it("splits the moment into local date and HH:mm", () => {
    expect(toLocalInput("2026-11-04T14:00:00Z", MOSCOW)).toEqual({
      date: "2026-11-04",
      time: "17:00",
    });
    expect(toLocalInput("2026-11-04T14:00:00Z", VLADIVOSTOK)).toEqual({
      date: "2026-11-05",
      time: "00:00",
    });
  });

  it("uses the offset in effect on that date", () => {
    expect(toLocalInput("2026-07-15T12:00:00Z", NEW_YORK)).toEqual({
      date: "2026-07-15",
      time: "08:00",
    });
    expect(toLocalInput("2026-01-15T12:00:00Z", NEW_YORK)).toEqual({
      date: "2026-01-15",
      time: "07:00",
    });
  });
});

describe("fromLocalInput", () => {
  it("converts local wall-clock time to a UTC ISO string ending in Z", () => {
    expect(fromLocalInput("2026-11-04", "17:00", MOSCOW)).toBe("2026-11-04T14:00:00Z");
    expect(fromLocalInput("2026-11-05", "00:00", VLADIVOSTOK)).toBe("2026-11-04T14:00:00Z");
  });

  it("uses the offset in effect on that date", () => {
    expect(fromLocalInput("2026-07-15", "08:00", NEW_YORK)).toBe("2026-07-15T12:00:00Z");
    expect(fromLocalInput("2026-01-15", "07:00", NEW_YORK)).toBe("2026-01-15T12:00:00Z");
  });

  it("resolves a time skipped by the spring change with the offset before it", () => {
    // 02:30 does not exist in New York on 8 Mar 2026: the clocks jump from 02:00 to 03:00.
    expect(fromLocalInput("2026-03-08", "02:30", NEW_YORK)).toBe("2026-03-08T07:30:00Z");
  });

  it("resolves a time repeated by the autumn change to the earlier instant", () => {
    // 01:30 happens twice in New York on 1 Nov 2026; the first one is still EDT.
    expect(fromLocalInput("2026-11-01", "01:30", NEW_YORK)).toBe("2026-11-01T05:30:00Z");
  });
});

describe("toLocalInput and fromLocalInput round trip", () => {
  it.each([
    [MOSCOW, "2026-07-15T09:30:00Z"],
    [MOSCOW, "2026-01-15T09:30:00Z"],
    // Summer: 09:45 on 16 Jul, so the local date is the next day.
    [VLADIVOSTOK, "2026-07-15T23:45:00Z"],
    [VLADIVOSTOK, "2026-01-15T23:45:00Z"],
    [NEW_YORK, "2026-07-15T12:00:00Z"],
    [NEW_YORK, "2026-01-15T12:00:00Z"],
  ])("keeps %s at %s", (zone, moment) => {
    const { date, time } = toLocalInput(moment, zone);
    expect(fromLocalInput(date, time, zone)).toBe(moment);
  });
});
