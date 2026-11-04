import { describe, expect, it } from "vitest";

import { NOTIFICATION_TEXT, PRIORITIES, pluralize, ROLE_LABELS } from "./labels";

describe("PRIORITIES", () => {
  it("lists the four priorities in order with short codes", () => {
    expect(PRIORITIES).toEqual([
      { value: 1, label: "P1 Срочно", short: "P1" },
      { value: 2, label: "P2 Высокий", short: "P2" },
      { value: 3, label: "P3 Обычный", short: "P3" },
      { value: 4, label: "P4 Низкий", short: "P4" },
    ]);
  });
});

describe("ROLE_LABELS", () => {
  it("names each role in Russian", () => {
    expect(ROLE_LABELS).toEqual({
      owner: "Владелец",
      editor: "Редактор",
      viewer: "Читатель",
    });
  });
});

describe("NOTIFICATION_TEXT", () => {
  it("covers every notification kind", () => {
    expect(Object.keys(NOTIFICATION_TEXT).sort()).toEqual(
      [
        "board_added",
        "event_added",
        "event_deleted",
        "event_reminder",
        "event_removed",
        "event_updated",
        "task_assigned",
        "task_commented",
        "task_due",
        "task_reminder",
        "task_updated",
      ].sort(),
    );
  });

  it("inserts the title into each kind's text", () => {
    const title = "Созвон";
    expect(NOTIFICATION_TEXT.event_added?.(title)).toBe("Новое совместное событие: Созвон");
    expect(NOTIFICATION_TEXT.event_updated?.(title)).toBe("Изменилось событие: Созвон");
    expect(NOTIFICATION_TEXT.event_deleted?.(title)).toBe("Событие удалено: Созвон");
    expect(NOTIFICATION_TEXT.event_removed?.(title)).toBe("Вас убрали из события: Созвон");
    expect(NOTIFICATION_TEXT.event_reminder?.(title)).toBe("Скоро начнётся: Созвон");
    expect(NOTIFICATION_TEXT.task_assigned?.(title)).toBe("Вам назначена задача: Созвон");
    expect(NOTIFICATION_TEXT.task_updated?.(title)).toBe("Изменилась задача: Созвон");
    expect(NOTIFICATION_TEXT.task_commented?.(title)).toBe("Новый комментарий: Созвон");
    expect(NOTIFICATION_TEXT.task_due?.(title)).toBe("Сегодня срок: Созвон");
    expect(NOTIFICATION_TEXT.task_reminder?.(title)).toBe("Напоминание о задаче: Созвон");
    expect(NOTIFICATION_TEXT.board_added?.(title)).toBe("Вас добавили на доску: Созвон");
  });
});

describe("pluralize", () => {
  const plural = (count: number) => pluralize(count, "задача", "задачи", "задач");

  it.each([
    [1, "задача"],
    [2, "задачи"],
    [5, "задач"],
    [11, "задач"],
    [21, "задача"],
    [22, "задачи"],
    [25, "задач"],
    [112, "задач"],
  ])("returns the right form for %i", (count, word) => {
    expect(plural(count)).toBe(word);
  });

  it("uses the many form for zero and for the teens", () => {
    expect(plural(0)).toBe("задач");
    expect(plural(12)).toBe("задач");
    expect(plural(14)).toBe("задач");
  });

  it("uses the one form for 101 and the few form for 103", () => {
    expect(plural(101)).toBe("задача");
    expect(plural(103)).toBe("задачи");
  });
});
