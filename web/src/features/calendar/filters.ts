import { useCallback, useSyncExternalStore } from "react";

/** Which categories and whether the task layer are shown. Remembered per browser. */
export type CalendarFilters = { hiddenCategories: string[]; tasksHidden: boolean };

const STORAGE_KEY = "planny.calendar-filters";
const NOTHING_HIDDEN: CalendarFilters = { hiddenCategories: [], tasksHidden: false };

const listeners = new Set<() => void>();
let current: CalendarFilters | null = null;

function isFilters(value: unknown): value is CalendarFilters {
  if (typeof value !== "object" || value === null) return false;
  const { hiddenCategories, tasksHidden } = value as Partial<CalendarFilters>;
  return Array.isArray(hiddenCategories) && typeof tasksHidden === "boolean";
}

/** Storage is a convenience: when it is unavailable, the filters just aren't remembered. */
function read(): CalendarFilters {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null");
    return isFilters(saved) ? saved : NOTHING_HIDDEN;
  } catch {
    return NOTHING_HIDDEN;
  }
}

function write(next: CalendarFilters): void {
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Remembered until the page reloads.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): CalendarFilters {
  current ??= read();
  return current;
}

/** Tests start from a clean browser. */
export function resetCalendarFilters(): void {
  current = null;
}

export function useCalendarFilters() {
  const filters = useSyncExternalStore(subscribe, snapshot);

  const setCategoryShown = useCallback((id: string, shown: boolean) => {
    const { hiddenCategories, tasksHidden } = snapshot();
    const others = hiddenCategories.filter((hidden) => hidden !== id);
    write({ hiddenCategories: shown ? others : [...others, id], tasksHidden });
  }, []);

  const setTasksShown = useCallback((shown: boolean) => {
    write({ ...snapshot(), tasksHidden: !shown });
  }, []);

  return { filters, setCategoryShown, setTasksShown };
}
