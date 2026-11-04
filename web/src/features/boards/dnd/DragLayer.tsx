import {
  DndContext,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import type { BoardColumn, TaskSummary } from "../../../api/client";
import { holdUpdates, releaseUpdates } from "../../sync/hold";
import { useMoveCard } from "../../tasks/api";
import { useMoveColumn } from "../api";
import {
  DragContext,
  type CardDrag,
  type ColumnDrag,
  type Drag,
  type DragApi,
} from "./dragContext";
import {
  afterIdAt,
  boxAt,
  homeOf,
  samePlace,
  stepCard,
  stepColumn,
  type ColumnCards,
  type Place,
  type Point,
  type Step,
} from "./placement";
import styles from "./DragLayer.module.css";

const LONG_PRESS_MS = 250;
const COLUMN_REACH = 24;
const STEPS: Record<string, Step> = {
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
};

const CARD_HINT = "Стрелки переносят карточку, пробел отпускает, Esc отменяет";
const COLUMN_HINT = "Стрелки переносят колонку, пробел отпускает, Esc отменяет";

function layoutOf(root: HTMLElement | null): ColumnCards[] {
  return [...(root?.querySelectorAll<HTMLElement>("[data-drop-column]") ?? [])].map((element) => ({
    columnId: element.dataset.dropColumn ?? "",
    cardIds: [...element.querySelectorAll<HTMLElement>("[data-card-id]")].map(
      (card) => card.dataset.cardId ?? "",
    ),
  }));
}

function cardPlaceAt(root: HTMLElement | null, point: Point, cardId: string): Place | null {
  const columns = [...(root?.querySelectorAll<HTMLElement>("[data-drop-column]") ?? [])];
  const columnId = boxAt(
    columns.map((element) => {
      const { left, right, top, bottom } = element.getBoundingClientRect();
      return { id: element.dataset.dropColumn ?? "", left, right, top, bottom };
    }),
    point,
    COLUMN_REACH,
  );
  const column = columns.find((element) => element.dataset.dropColumn === columnId);
  if (!column || columnId === null) return null;
  const cards = [...column.querySelectorAll<HTMLElement>("[data-card-id]")].map((element) => {
    const { top, bottom } = element.getBoundingClientRect();
    return { id: element.dataset.cardId ?? "", start: top, end: bottom };
  });
  return { columnId, afterId: afterIdAt(cards, point.y, cardId) };
}

function columnPlaceAt(root: HTMLElement | null, point: Point, columnId: string): string | null {
  const columns = [...(root?.querySelectorAll<HTMLElement>("[data-drop-column]") ?? [])].map(
    (element) => {
      const { left, right } = element.getBoundingClientRect();
      return { id: element.dataset.dropColumn ?? "", start: left, end: right };
    },
  );
  return afterIdAt(columns, point.x, columnId);
}

function cardCaption(place: Place, columns: BoardColumn[], tasks: () => Map<string, string>) {
  const column = columns.find((item) => item.id === place.columnId)?.name ?? "";
  const after = place.afterId ? tasks().get(place.afterId) : undefined;
  return after ? `${column}, после карточки «${after}»` : `${column}, в начале`;
}

function titlesOf(root: HTMLElement | null): Map<string, string> {
  const titles = new Map<string, string>();
  for (const element of root?.querySelectorAll<HTMLElement>("[data-card-id]") ?? []) {
    titles.set(element.dataset.cardId ?? "", element.dataset.cardTitle ?? "");
  }
  return titles;
}

export type DragLayerProps = {
  boardId: string;
  columns: BoardColumn[];
  /** The list view stacks its columns, Kanban lays them out in a row. */
  stacked: boolean;
  readOnly: boolean;
  preview: (drag: Drag) => ReactNode;
  children: ReactNode;
};

/**
 * Cards don't shift while something is dragged: the place shows as a line, so the geometry stays
 * the one the user sees, and it is read from the page at the moment of use. dnd-kit brings the
 * sensors, the overlay and the auto-scroll. Keyboard dragging is the same state driven by keys.
 */
export function DragLayer({
  boardId,
  columns,
  stacked,
  readOnly,
  preview,
  children,
}: DragLayerProps) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const refocus = useRef<string | null>(null);
  const moveCard = useMoveCard();
  const moveColumn = useMoveColumn(boardId);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: LONG_PRESS_MS, tolerance: 8 },
    }),
  );
  // Collision detection is where dnd-kit reveals the pointer, and scrolling doesn't distort it.
  const pointer = useRef<Point | null>(null);
  const detect = useMemo<CollisionDetection>(
    () =>
      ({ pointerCoordinates, droppableContainers }) => {
        if (pointerCoordinates) pointer.current = pointerCoordinates;
        const here = pointerCoordinates;
        if (!here) return [];
        const over = droppableContainers.find((container) => {
          const node = container.node.current;
          const box = (node?.closest("[data-drop-column]") ?? node)?.getBoundingClientRect();
          return (
            box &&
            here.x >= box.left &&
            here.x <= box.right &&
            here.y >= box.top &&
            here.y <= box.bottom
          );
        });
        return over ? [{ id: over.id }] : [];
      },
    [],
  );

  const finish = useCallback(() => {
    setDrag(null);
    releaseUpdates();
  }, []);

  // Leaving the view in the middle of a drag must not stop updates for the rest of the session.
  useEffect(() => releaseUpdates, []);

  const dropCard = useCallback(
    (current: CardDrag) => {
      const { task, place } = current;
      const home = homeOf(layoutOf(root.current), task.id);
      if (!place || samePlace(place, home)) {
        refocus.current = null;
        return;
      }
      const column = columns.find((item) => item.id === place.columnId);
      moveCard.mutate(
        {
          task,
          columnId: place.columnId,
          columnIsDone: column?.is_done ?? false,
          afterId: place.afterId,
        },
        { onSettled: () => (refocus.current = null) },
      );
    },
    [columns, moveCard],
  );

  const dropColumn = useCallback(
    (current: ColumnDrag) => {
      const ids = columns.map((column) => column.id);
      const index = ids.indexOf(current.column.id);
      const home = index > 0 ? (ids[index - 1] ?? null) : null;
      if (current.afterId === undefined || current.afterId === home) {
        refocus.current = null;
        return;
      }
      moveColumn.mutate(
        { columnId: current.column.id, afterId: current.afterId },
        { onSettled: () => (refocus.current = null) },
      );
    },
    [columns, moveColumn],
  );

  const placeAtPointer = useCallback((current: Drag, point: Point): Drag => {
    if (current.kind === "card") {
      const place = cardPlaceAt(root.current, point, current.task.id);
      return samePlace(place, current.place) ? current : { ...current, place };
    }
    const afterId = columnPlaceAt(root.current, point, current.column.id);
    return afterId === current.afterId ? current : { ...current, afterId };
  }, []);

  const start = ({ active }: DragStartEvent) => {
    const data = active.data.current as
      | { task: TaskSummary; column?: undefined }
      | { column: BoardColumn; task?: undefined }
      | undefined;
    if (!data) return;
    holdUpdates();
    pointer.current = null;
    if (data.task) {
      setDrag({ kind: "card", task: data.task, place: null, viaKeyboard: false });
    } else if (data.column) {
      setDrag({ kind: "column", column: data.column, afterId: undefined, viaKeyboard: false });
    }
  };

  const move = () => {
    const point = pointer.current;
    if (point) setDrag((current) => current && placeAtPointer(current, point));
  };

  const end = () => {
    const point = pointer.current;
    if (drag) {
      const landed = point ? placeAtPointer(drag, point) : drag;
      if (landed.kind === "card") dropCard(landed);
      else dropColumn(landed);
    }
    finish();
  };

  const liftCard = useCallback((task: TaskSummary) => {
    const place = homeOf(layoutOf(root.current), task.id);
    if (!place) return;
    holdUpdates();
    setAnnouncement(`Карточка «${task.title}» взята. ${CARD_HINT}`);
    setDrag({ kind: "card", task, place, viaKeyboard: true });
  }, []);

  const liftColumn = useCallback(
    (column: BoardColumn) => {
      const index = columns.findIndex((item) => item.id === column.id);
      const afterId = index > 0 ? (columns[index - 1]?.id ?? null) : null;
      holdUpdates();
      setAnnouncement(`Колонка «${column.name}» взята. ${COLUMN_HINT}`);
      setDrag({ kind: "column", column, afterId, viaKeyboard: true });
    },
    [columns],
  );

  // Keys are taken before the page: arrows must not scroll, and Esc must not close anything.
  useEffect(() => {
    if (!drag?.viaKeyboard) return;
    const onKey = (event: KeyboardEvent) => {
      const step = STEPS[event.key];
      if (event.key === " " || event.key === "Enter") {
        if (drag.kind === "card") {
          refocus.current = drag.task.id;
          dropCard(drag);
          setAnnouncement("Карточка отпущена");
        } else {
          refocus.current = drag.column.id;
          dropColumn(drag);
          setAnnouncement("Колонка отпущена");
        }
        finish();
      } else if (event.key === "Escape") {
        setAnnouncement("Перенос отменён");
        finish();
      } else if (step && drag.kind === "card" && drag.place) {
        const place = stepCard(layoutOf(root.current), drag.place, drag.task.id, step, {
          stacked,
        });
        setAnnouncement(cardCaption(place, columns, () => titlesOf(root.current)));
        setDrag({ ...drag, place });
      } else if (step && drag.kind === "column" && drag.afterId !== undefined) {
        const ids = columns.map((column) => column.id);
        const afterId = stepColumn(ids, drag.column.id, drag.afterId, step);
        const name = columns.find((column) => column.id === afterId)?.name;
        setAnnouncement(name ? `После колонки «${name}»` : "В начале доски");
        setDrag({ ...drag, afterId });
      } else if (event.key === "Tab") {
        setAnnouncement("Перенос отменён");
        finish();
        return;
      } else {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
    };
    const onPress = () => {
      setAnnouncement("Перенос отменён");
      finish();
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onPress, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onPress, true);
    };
  }, [columns, drag, dropCard, dropColumn, finish, stacked]);

  // Auto-scroll moves the columns under a pointer that stands still, and the line has to follow.
  const dragging = drag !== null && !drag.viaKeyboard;
  useEffect(() => {
    if (!dragging) return;
    const onScroll = () => {
      const point = pointer.current;
      if (point) setDrag((current) => current && placeAtPointer(current, point));
    };
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, [dragging, placeAtPointer]);

  // The line may run out of a scrolling column while the arrows push it.
  useEffect(() => {
    if (drag?.viaKeyboard) {
      root.current?.querySelector("[data-drop-line]")?.scrollIntoView?.({ block: "nearest" });
    }
  }, [drag]);

  const value = useMemo<DragApi>(
    () => ({
      drag,
      readOnly,
      liftCard,
      liftColumn,
      wantsFocus: (id) => refocus.current === id,
      onHandleKeyUp: (event: ReactKeyboardEvent) => {
        // The space that dropped something must not click the button under focus.
        if (event.key === " ") event.preventDefault();
      },
    }),
    [drag, liftCard, liftColumn, readOnly],
  );

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={detect}
      onDragStart={start}
      onDragMove={move}
      onDragEnd={end}
      onDragCancel={finish}
      accessibility={{ screenReaderInstructions: { draggable: "" } }}
    >
      <DragContext.Provider value={value}>
        <div ref={root} className={styles.root} data-dragging={drag ? "" : undefined}>
          {children}
        </div>
      </DragContext.Provider>
      <DragOverlay dropAnimation={null}>
        {drag && !drag.viaKeyboard ? preview(drag) : null}
      </DragOverlay>
      <div className={styles.announcer} role="status" aria-live="assertive">
        {announcement}
      </div>
    </DndContext>
  );
}
