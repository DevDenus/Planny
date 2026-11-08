import { describe, expect, it } from "vitest";

import type { EventCard, TaskCard } from "../../api/client";
import { newDraft } from "../calendar/EventForm";
import {
  cardFromEventDraft,
  cardFromTaskDraft,
  eventDraftFromCard,
  eventProposedOnBase,
  taskDraftFromCard,
  taskProposedOnBase,
} from "./cards";

const ZONE = "Europe/Moscow";
const ME = "u1";
const PERSONAL = "board-personal";

const task = (overrides: Partial<TaskCard> = {}): TaskCard => ({
  kind: "task",
  title: "Купить молоко",
  priority: 3,
  ...overrides,
});

const event = (overrides: Partial<EventCard> = {}): EventCard => ({
  kind: "event",
  title: "Ужин",
  all_day: false,
  timezone: ZONE,
  start_at: "2026-11-06T16:00:00Z",
  end_at: "2026-11-06T17:30:00Z",
  ...overrides,
});

describe("taskDraftFromCard", () => {
  it("falls back to the personal board and reads the deadline in the zone", () => {
    const draft = taskDraftFromCard(
      task({ due_at: "2026-11-06T16:00:00Z", priority: 1, checklist: ["a"] }),
      ZONE,
      PERSONAL,
    );
    expect(draft).toMatchObject({
      title: "Купить молоко",
      boardId: PERSONAL,
      columnId: "",
      priority: "1",
      dueDate: "2026-11-06",
      dueTime: "19:00",
    });
  });

  it("keeps a date-only deadline and the board of the card", () => {
    const draft = taskDraftFromCard(
      task({ board_id: "b2", column_id: "c2", due_date: "2026-11-09", assignee_ids: ["u2"] }),
      ZONE,
      PERSONAL,
    );
    expect(draft).toMatchObject({
      boardId: "b2",
      columnId: "c2",
      dueDate: "2026-11-09",
      dueTime: "",
      assigneeIds: ["u2"],
    });
  });
});

describe("cardFromTaskDraft", () => {
  it("returns a time as an instant and a bare date as a date", () => {
    const timed = taskDraftFromCard(task({ due_at: "2026-11-06T16:00:00Z" }), ZONE, PERSONAL);
    expect(cardFromTaskDraft(timed, ["x"], ZONE)).toMatchObject({
      kind: "task",
      board_id: PERSONAL,
      column_id: null,
      due_at: "2026-11-06T16:00:00Z",
      due_date: null,
      checklist: ["x"],
    });
    const dated = taskDraftFromCard(task({ due_date: "2026-11-09" }), ZONE, PERSONAL);
    expect(cardFromTaskDraft(dated, [], ZONE)).toMatchObject({
      due_at: null,
      due_date: "2026-11-09",
    });
  });
});

describe("taskProposedOnBase", () => {
  it("takes the card's fields and keeps labels, reminder and column the card doesn't hold", () => {
    const base = {
      ...taskDraftFromCard(task({ board_id: "b1", column_id: "c1" }), ZONE, PERSONAL),
      labelIds: ["l1"],
      reminderDate: "2026-11-05",
      reminderTime: "09:00",
    };
    const proposed = taskProposedOnBase(
      task({ board_id: "b1", title: "Новое", priority: 2 }),
      base,
      ZONE,
    );
    expect(proposed).toMatchObject({
      title: "Новое",
      priority: "2",
      columnId: "c1",
      labelIds: ["l1"],
      reminderDate: "2026-11-05",
      reminderTime: "09:00",
    });
  });

  it("drops the labels and the column of another board", () => {
    const base = {
      ...taskDraftFromCard(task({ board_id: "b1" }), ZONE, PERSONAL),
      labelIds: ["l1"],
    };
    const proposed = taskProposedOnBase(task({ board_id: "b2" }), base, ZONE);
    expect(proposed).toMatchObject({ boardId: "b2", columnId: "", labelIds: [] });
  });
});

describe("eventDraftFromCard", () => {
  it("reads a timed event in the zone and adds the current user to the participants", () => {
    const draft = eventDraftFromCard(event({ participant_ids: ["u2", ME] }), ZONE, ME);
    expect(draft).toMatchObject({
      allDay: false,
      startDate: "2026-11-06",
      startTime: "19:00",
      endDate: "2026-11-06",
      endTime: "20:30",
      participantIds: [ME, "u2"],
      repeat: "",
      reminder: "",
    });
  });

  it("reads an all-day event by its dates", () => {
    const draft = eventDraftFromCard(
      event({
        all_day: true,
        start_at: null,
        end_at: null,
        start_date: "2026-11-07",
        end_date: "2026-11-09",
      }),
      ZONE,
      ME,
    );
    expect(draft).toMatchObject({
      allDay: true,
      startDate: "2026-11-07",
      endDate: "2026-11-09",
      participantIds: [ME],
    });
  });

  it("maps a series ending by a date or by a count", () => {
    expect(
      eventDraftFromCard(
        event({ recurrence: { freq: "weekly", until: "2026-12-31", count: null } }),
        ZONE,
        ME,
      ),
    ).toMatchObject({ repeat: "weekly", seriesEnd: "until", until: "2026-12-31", count: "" });
    expect(
      eventDraftFromCard(event({ recurrence: { freq: "daily", until: null, count: 5 } }), ZONE, ME),
    ).toMatchObject({ repeat: "daily", seriesEnd: "count", until: "", count: "5" });
    expect(eventDraftFromCard(event({ recurrence: { freq: "monthly" } }), ZONE, ME)).toMatchObject({
      repeat: "monthly",
      seriesEnd: "never",
    });
  });

  it("takes the first reminder, or the nearest option to it", () => {
    expect(eventDraftFromCard(event({ reminder_minutes: [30, 5] }), ZONE, ME).reminder).toBe("30");
    expect(eventDraftFromCard(event({ reminder_minutes: [0] }), ZONE, ME).reminder).toBe("0");
    expect(eventDraftFromCard(event({ reminder_minutes: [20] }), ZONE, ME).reminder).toBe("15");
    expect(eventDraftFromCard(event({ reminder_minutes: [100] }), ZONE, ME).reminder).toBe("60");
    expect(eventDraftFromCard(event({ reminder_minutes: [10000] }), ZONE, ME).reminder).toBe(
      "1440",
    );
  });
});

describe("cardFromEventDraft", () => {
  it("is the reverse of eventDraftFromCard, without the current user", () => {
    const source = event({
      participant_ids: ["u2"],
      recurrence: { freq: "weekly", until: null, count: 4 },
      reminder_minutes: [15],
      location: "Дома",
      description: "Без опозданий",
    });
    const card = cardFromEventDraft(eventDraftFromCard(source, ZONE, ME), ZONE, ME);
    expect(card).toEqual({
      ...source,
      start_date: null,
      end_date: null,
      recurrence: { freq: "weekly", until: null, count: 4 },
    });
  });

  it("keeps all-day dates", () => {
    const source = event({
      all_day: true,
      start_at: null,
      end_at: null,
      start_date: "2026-11-07",
      end_date: "2026-11-09",
    });
    expect(cardFromEventDraft(eventDraftFromCard(source, ZONE, ME), ZONE, ME)).toMatchObject({
      all_day: true,
      start_date: "2026-11-07",
      end_date: "2026-11-09",
      start_at: null,
      end_at: null,
    });
  });

  it("is null while the draft is not a valid event", () => {
    expect(
      cardFromEventDraft({ ...newDraft(ME, "2026-11-06", undefined), title: "" }, ZONE, ME),
    ).toBeNull();
    expect(
      cardFromEventDraft({ ...newDraft(ME, "", undefined), title: "Ужин" }, ZONE, ME),
    ).toBeNull();
  });
});

describe("eventProposedOnBase", () => {
  it("keeps the category of the saved event", () => {
    const base = { ...eventDraftFromCard(event(), ZONE, ME), categoryId: "cat1" };
    expect(eventProposedOnBase(event({ title: "Другое" }), base, ZONE, ME)).toMatchObject({
      title: "Другое",
      categoryId: "cat1",
    });
  });
});
