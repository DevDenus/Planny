import { describe, expect, it } from "vitest";

import {
  afterIdAt,
  boxAt,
  homeOf,
  samePlace,
  stepCard,
  stepColumn,
  type Box,
  type ColumnCards,
  type Span,
} from "./placement";

const KANBAN = { stacked: false };
const LIST = { stacked: true };

describe("afterIdAt", () => {
  const spans: Span[] = [
    { id: "a", start: 0, end: 10 },
    { id: "b", start: 10, end: 20 },
  ];

  it("gives null above the first card", () => {
    expect(afterIdAt(spans, 2, "x")).toBeNull();
  });

  it("gives the last card whose middle lies above the point", () => {
    expect(afterIdAt(spans, 6, "x")).toBe("a");
    expect(afterIdAt(spans, 16, "x")).toBe("b");
  });

  it("leaves the dragged card out, so it cannot be the card before itself", () => {
    // Counted, "a" would stand before the point and the answer would be "a".
    expect(afterIdAt(spans, 6, "a")).toBeNull();
  });

  it("gives null for an empty list", () => {
    expect(afterIdAt([], 5, "x")).toBeNull();
  });
});

describe("boxAt", () => {
  const boxes: Box[] = [
    { id: "left", left: 0, right: 10, top: 0, bottom: 10 },
    { id: "right", left: 20, right: 30, top: 0, bottom: 10 },
  ];

  it("gives the box under the point", () => {
    expect(boxAt(boxes, { x: 5, y: 5 })).toBe("left");
    expect(boxAt(boxes, { x: 25, y: 5 })).toBe("right");
  });

  it("gives null for a miss when there is no reach", () => {
    expect(boxAt(boxes, { x: 15, y: 5 })).toBeNull();
  });

  it("sends a point in the gap within reach to the nearest box", () => {
    // 4 pixels from the left box and 6 from the right one, and the other way round.
    expect(boxAt(boxes, { x: 14, y: 5 }, 10)).toBe("left");
    expect(boxAt(boxes, { x: 16, y: 5 }, 10)).toBe("right");
  });

  it("gives null beyond the reach", () => {
    expect(boxAt(boxes, { x: 14, y: 5 }, 3)).toBeNull();
  });
});

describe("samePlace", () => {
  it("compares the column and the card before the place", () => {
    expect(samePlace({ columnId: "c1", afterId: "a" }, { columnId: "c1", afterId: "a" })).toBe(
      true,
    );
    expect(samePlace({ columnId: "c1", afterId: "a" }, { columnId: "c1", afterId: null })).toBe(
      false,
    );
    expect(samePlace({ columnId: "c1", afterId: null }, { columnId: "c2", afterId: null })).toBe(
      false,
    );
  });

  it("treats two missing places as the same, and a place and none as different", () => {
    expect(samePlace(null, null)).toBe(true);
    expect(samePlace({ columnId: "c1", afterId: null }, null)).toBe(false);
  });
});

describe("homeOf", () => {
  const layout: ColumnCards[] = [
    { columnId: "c1", cardIds: ["a", "b"] },
    { columnId: "c2", cardIds: ["c"] },
  ];

  it("gives the card before it in its column", () => {
    expect(homeOf(layout, "b")).toEqual({ columnId: "c1", afterId: "a" });
  });

  it("gives no card before the first card of a column", () => {
    expect(homeOf(layout, "a")).toEqual({ columnId: "c1", afterId: null });
    expect(homeOf(layout, "c")).toEqual({ columnId: "c2", afterId: null });
  });

  it("gives null for a card that is not on the board", () => {
    expect(homeOf(layout, "missing")).toBeNull();
  });
});

describe("stepCard on Kanban", () => {
  const board: ColumnCards[] = [
    { columnId: "c1", cardIds: ["a", "b", "c"] },
    { columnId: "c2", cardIds: ["d", "e"] },
    { columnId: "c3", cardIds: ["f"] },
  ];

  it("moves up and down within a column", () => {
    // "a" is lifted from the top of c1, so the column holds "b" and "c" after it.
    const top = { columnId: "c1", afterId: null };
    const second = stepCard(board, top, "a", "down", KANBAN);
    expect(second).toEqual({ columnId: "c1", afterId: "b" });
    const bottom = stepCard(board, second, "a", "down", KANBAN);
    expect(bottom).toEqual({ columnId: "c1", afterId: "c" });
    expect(stepCard(board, bottom, "a", "up", KANBAN)).toEqual(second);
  });

  it("stops at the top and the bottom of a column", () => {
    const top = { columnId: "c1", afterId: null };
    expect(stepCard(board, top, "a", "up", KANBAN)).toEqual(top);
    const bottom = { columnId: "c1", afterId: "c" };
    expect(stepCard(board, bottom, "a", "down", KANBAN)).toEqual(bottom);
  });

  it("moves left and right to the neighbour at the same height", () => {
    // "b" is lifted from c1 after "a", the second place of its column.
    const place = { columnId: "c1", afterId: "a" };
    expect(stepCard(board, place, "b", "right", KANBAN)).toEqual({ columnId: "c2", afterId: "d" });
    expect(stepCard(board, place, "b", "left", KANBAN)).toEqual({
      columnId: "c1",
      afterId: "a",
    });
  });

  it("clamps the height to the end of a shorter neighbour", () => {
    // Place "e" is the third place of c2. c3 has one card, so the place becomes its end.
    const place = { columnId: "c2", afterId: "e" };
    expect(stepCard(board, place, "b", "right", KANBAN)).toEqual({ columnId: "c3", afterId: "f" });
  });

  it("stops at the first and the last column", () => {
    const first = { columnId: "c1", afterId: "a" };
    expect(stepCard(board, first, "b", "left", KANBAN)).toEqual(first);
    const last = { columnId: "c3", afterId: "f" };
    expect(stepCard(board, last, "b", "right", KANBAN)).toEqual(last);
  });

  it("leaves the dragged card out of the count of its column", () => {
    const column: ColumnCards[] = [{ columnId: "c1", cardIds: ["a", "b"] }];
    // With "b" lifted, "a" is alone: nothing lies under it, so the place does not move.
    const under = { columnId: "c1", afterId: "a" };
    expect(stepCard(column, under, "b", "down", KANBAN)).toEqual(under);
    // With "a" lifted, "b" is alone, so one step down from the top reaches its end.
    const top = { columnId: "c1", afterId: null };
    expect(stepCard(column, top, "a", "down", KANBAN)).toEqual({ columnId: "c1", afterId: "b" });
  });
});

describe("stepCard on the list", () => {
  const list: ColumnCards[] = [
    { columnId: "c1", cardIds: ["a", "b"] },
    { columnId: "c2", cardIds: ["c", "d"] },
  ];

  it("goes down from the end of a column to the top of the next one", () => {
    const end = { columnId: "c1", afterId: "a" };
    expect(stepCard(list, end, "b", "down", LIST)).toEqual({ columnId: "c2", afterId: null });
  });

  it("goes up from the top of a column to the end of the previous one", () => {
    const top = { columnId: "c2", afterId: null };
    expect(stepCard(list, top, "c", "up", LIST)).toEqual({ columnId: "c1", afterId: "b" });
  });

  it("stops at the top of the first column and the end of the last one", () => {
    const top = { columnId: "c1", afterId: null };
    expect(stepCard(list, top, "b", "up", LIST)).toEqual(top);
    const end = { columnId: "c2", afterId: "d" };
    expect(stepCard(list, end, "c", "down", LIST)).toEqual(end);
  });

  it("does nothing on left and right", () => {
    const place = { columnId: "c1", afterId: "a" };
    expect(stepCard(list, place, "b", "left", LIST)).toEqual(place);
    expect(stepCard(list, place, "b", "right", LIST)).toEqual(place);
  });
});

describe("stepColumn", () => {
  const columns = ["a", "b", "c"];

  it("moves a column to the right, one place at a time", () => {
    // "a" starts first, so after "b" is its first step right.
    expect(stepColumn(columns, "a", null, "right")).toBe("b");
    expect(stepColumn(columns, "a", "b", "right")).toBe("c");
  });

  it("moves a column to the left, one place at a time", () => {
    expect(stepColumn(columns, "c", "b", "left")).toBe("a");
    expect(stepColumn(columns, "b", "a", "left")).toBeNull();
  });

  it("stops at the first and the last place", () => {
    expect(stepColumn(columns, "a", null, "left")).toBeNull();
    expect(stepColumn(columns, "c", "b", "right")).toBe("b");
  });
});
