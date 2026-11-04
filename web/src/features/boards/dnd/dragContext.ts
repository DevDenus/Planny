import { createContext, useContext, type KeyboardEvent } from "react";

import type { BoardColumn, TaskSummary } from "../../../api/client";
import type { Place } from "./placement";

export type CardDrag = {
  kind: "card";
  task: TaskSummary;
  /** Null while the pointer is outside every column: a drop there cancels. */
  place: Place | null;
  viaKeyboard: boolean;
};

export type ColumnDrag = {
  kind: "column";
  column: BoardColumn;
  /** Undefined until the pointer has been seen. */
  afterId: string | null | undefined;
  viaKeyboard: boolean;
};

export type Drag = CardDrag | ColumnDrag;

export type DragApi = {
  drag: Drag | null;
  readOnly: boolean;
  liftCard: (task: TaskSummary) => void;
  liftColumn: (column: BoardColumn) => void;
  /**
   * A keyboard drop re-parents the element, and the DOM drops the focus with it. Until the move
   * settles, the card asks after each of its renders whether to take the focus back.
   */
  wantsFocus: (id: string) => boolean;
  onHandleKeyUp: (event: KeyboardEvent) => void;
};

export const DragContext = createContext<DragApi | null>(null);

export function useDragLayer(): DragApi {
  const value = useContext(DragContext);
  if (!value) throw new Error("useDragLayer needs a DragLayer above it");
  return value;
}
