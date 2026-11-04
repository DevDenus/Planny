/** Where a dragged thing lands, with no browser in it: the geometry comes in as plain numbers. */

export type Point = { x: number; y: number };
export type Span = { id: string; start: number; end: number };
export type Box = { id: string; left: number; right: number; top: number; bottom: number };
export type Place = { columnId: string; afterId: string | null };
export type ColumnCards = { columnId: string; cardIds: string[] };

/** What stands before the insertion point on an axis, leaving out the thing being dragged. */
export function afterIdAt(items: Span[], coordinate: number, activeId: string): string | null {
  let after: string | null = null;
  for (const item of items) {
    if (item.id === activeId) continue;
    if (coordinate < (item.start + item.end) / 2) break;
    after = item.id;
  }
  return after;
}

/**
 * The box under a point. `reach` forgives a miss by that many pixels, so a release in the gap
 * between two columns, or past the last one at the edge of the screen, still lands somewhere.
 */
export function boxAt(boxes: Box[], { x, y }: Point, reach = 0): string | null {
  let nearest: string | null = null;
  let best = Infinity;
  for (const box of boxes) {
    const away =
      Math.max(box.left - x, 0, x - box.right) + Math.max(box.top - y, 0, y - box.bottom);
    if (away <= reach && away < best) {
      nearest = box.id;
      best = away;
    }
  }
  return nearest;
}

export function samePlace(left: Place | null, right: Place | null): boolean {
  return left?.columnId === right?.columnId && left?.afterId === right?.afterId;
}

/** The place a card occupies now, the one a drop does nothing at. */
export function homeOf(layout: ColumnCards[], cardId: string): Place | null {
  for (const { columnId, cardIds } of layout) {
    const index = cardIds.indexOf(cardId);
    if (index >= 0) return { columnId, afterId: cardIds[index - 1] ?? null };
  }
  return null;
}

function withoutCard(layout: ColumnCards[], cardId: string): ColumnCards[] {
  return layout.map(({ columnId, cardIds }) => ({
    columnId,
    cardIds: cardIds.filter((id) => id !== cardId),
  }));
}

export type Step = "up" | "down" | "left" | "right";

/**
 * One arrow press. On Kanban left and right change the column at the same height. On the list
 * the columns stand one under another, so up and down run through them as one long list.
 */
export function stepCard(
  layout: ColumnCards[],
  place: Place,
  cardId: string,
  step: Step,
  { stacked }: { stacked: boolean },
): Place {
  const columns = withoutCard(layout, cardId);
  const columnIndex = columns.findIndex(({ columnId }) => columnId === place.columnId);
  const column = columns[columnIndex];
  if (!column) return place;
  // Places in a column: 0 is the top, n is after the n-th card.
  const here = place.afterId === null ? 0 : column.cardIds.indexOf(place.afterId) + 1;
  const at = (target: ColumnCards, index: number): Place => ({
    columnId: target.columnId,
    afterId: index <= 0 ? null : (target.cardIds[index - 1] ?? null),
  });

  if (step === "up" || step === "down") {
    const next = here + (step === "up" ? -1 : 1);
    if (next >= 0 && next <= column.cardIds.length) return at(column, next);
    const neighbour = stacked ? columns[columnIndex + (step === "up" ? -1 : 1)] : undefined;
    if (!neighbour) return place;
    return at(neighbour, step === "up" ? neighbour.cardIds.length : 0);
  }
  if (stacked) return place;
  const neighbour = columns[columnIndex + (step === "left" ? -1 : 1)];
  return neighbour ? at(neighbour, Math.min(here, neighbour.cardIds.length)) : place;
}

export function stepColumn(
  columnIds: string[],
  columnId: string,
  afterId: string | null,
  step: Step,
) {
  const rest = columnIds.filter((id) => id !== columnId);
  const here = afterId === null ? 0 : rest.indexOf(afterId) + 1;
  const next = here + (step === "left" ? -1 : step === "right" ? 1 : 0);
  if (next < 0 || next > rest.length) return afterId;
  return next === 0 ? null : (rest[next - 1] ?? null);
}
