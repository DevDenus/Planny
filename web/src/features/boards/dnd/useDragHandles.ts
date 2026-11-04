import { useDraggable, useDroppable } from "@dnd-kit/core";
import { useEffect, useRef, type KeyboardEvent } from "react";

import type { BoardColumn, TaskSummary } from "../../../api/client";
import { useDragLayer } from "./dragContext";

/** A card that can be picked up by pointer or space. */
export function useCardHandle(task: TaskSummary) {
  const { drag, readOnly, liftCard, wantsFocus, onHandleKeyUp } = useDragLayer();
  const { setNodeRef, listeners } = useDraggable({
    id: `card:${task.id}`,
    data: { task },
    disabled: readOnly,
  });
  const focusTarget = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (wantsFocus(task.id)) focusTarget.current?.focus();
  });

  const dragged = drag?.kind === "card" && drag.task.id === task.id;
  return {
    attach: setNodeRef,
    focusTarget,
    listeners: readOnly ? undefined : listeners,
    draggable: !readOnly,
    dragged,
    lifted: dragged && drag.viaKeyboard,
    keys: readOnly
      ? {}
      : {
          onKeyDown: (event: KeyboardEvent) => {
            if (event.key !== " " || drag) return;
            event.preventDefault();
            liftCard(task);
          },
          onKeyUp: onHandleKeyUp,
        },
  };
}

/** A column header that can be picked up by pointer or space. */
export function useColumnHandle(column: BoardColumn) {
  const { drag, readOnly, liftColumn, wantsFocus, onHandleKeyUp } = useDragLayer();
  const { setNodeRef, listeners } = useDraggable({
    id: `column:${column.id}`,
    data: { column },
    disabled: readOnly,
  });
  const focusTarget = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (wantsFocus(column.id)) focusTarget.current?.focus();
  });

  const dragged = drag?.kind === "column" && drag.column.id === column.id;
  return {
    attach: setNodeRef,
    focusTarget,
    listeners: readOnly ? undefined : listeners,
    dragged,
    keys: readOnly
      ? {}
      : {
          onKeyDown: (event: KeyboardEvent) => {
            if (event.key !== " " || drag) return;
            event.preventDefault();
            liftColumn(column);
          },
          onKeyUp: onHandleKeyUp,
        },
  };
}

/**
 * The element dnd-kit scrolls near its edges. `linePosition` says where the insertion line of a
 * dragged card or column goes relative to this column.
 */
export function useDropColumn(column: BoardColumn) {
  const { drag } = useDragLayer();
  const { setNodeRef } = useDroppable({ id: `drop:${column.id}` });
  const targeted = drag?.kind === "card" && drag.place?.columnId === column.id;
  return {
    attach: setNodeRef,
    targeted,
    /** The card after which the line stands: null is the top, undefined is no line here. */
    lineAfter: targeted ? drag.place?.afterId : undefined,
    /** A column is being dragged and belongs right after this one. */
    columnLineAfter: drag?.kind === "column" && drag.afterId === column.id,
    columnLineFirst: drag?.kind === "column" && drag.afterId === null,
  };
}
