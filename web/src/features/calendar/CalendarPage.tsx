import { Plus } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import type { CalendarItem } from "../../api/client";
import { Button, LoadError, SegmentedControl } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { fromLocalInput, localDate } from "../tasks/dates";
import { useTaskParam } from "../tasks/taskLinks";
import { useNow } from "../tasks/useNow";
import { useCalendarItems, useCategories } from "./api";
import { FiltersButton } from "./CalendarFilters";
import { CalendarGrid } from "./CalendarGrid";
import styles from "./CalendarPage.module.css";
import { CompactMonth } from "./CompactMonth";
import { DayPanel } from "./DayPanel";
import { useEventParam } from "./eventLinks";
import { useCalendarFilters } from "./filters";
import { colorsOf, isShown } from "./items";
import { PeriodHeader } from "./PeriodHeader";
import { viewRange, type CalendarView } from "./period";
import { useIsPhone } from "./useIsPhone";

const VIEWS: { value: CalendarView; label: string }[] = [
  { value: "month", label: "Месяц" },
  { value: "week", label: "Неделя" },
  { value: "day", label: "День" },
];
const DAY_FORMAT = /^\d{4}-\d{2}-\d{2}$/;

/** The period lives in the URL: a reload and the back button keep it. */
function useCalendarPeriod(today: string) {
  const [params, setParams] = useSearchParams();
  const asked = params.get("view");
  const view = VIEWS.find((item) => item.value === asked)?.value ?? "month";
  const askedDay = params.get("day") ?? "";
  const day = DAY_FORMAT.test(askedDay) ? askedDay : today;

  const change = useCallback(
    (name: "view" | "day", value: string) => {
      setParams(
        (current) => {
          current.set(name, value);
          return current;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return {
    view,
    day,
    setView: (next: CalendarView) => change("view", next),
    setDay: useCallback((next: string) => change("day", next), [change]),
  };
}

export function CalendarPage() {
  const { data: user } = useCurrentUser();
  const timeZone = user?.timezone ?? "UTC";
  const now = useNow();
  const today = localDate(now, timeZone);
  const { view, day, setView, setDay } = useCalendarPeriod(today);
  const phone = useIsPhone();
  const shownView = phone ? "month" : view;
  const { first, end } = viewRange(shownView, day);
  const {
    data: items,
    isError,
    isPlaceholderData,
    refetch,
  } = useCalendarItems({
    from: fromLocalInput(first, "00:00", timeZone),
    to: fromLocalInput(end, "00:00", timeZone),
  });
  // The grid keeps the previous period while the new one loads; that is not this period's answer.
  const loaded = items !== undefined && !isError && !isPlaceholderData;
  const { data: categories } = useCategories();
  const { filters } = useCalendarFilters();
  const { open: openEvent, create } = useEventParam();
  const { open: openTask } = useTaskParam();

  const colors = useMemo(() => colorsOf(categories), [categories]);
  const shown = useMemo(
    () => (items ?? []).filter((item) => isShown(item, filters)),
    [items, filters],
  );
  const openItem = (item: CalendarItem) => {
    if (item.type === "task") openTask(item.task_id);
    else openEvent(item.event_id, item.occurrence_start);
  };

  return (
    <section className={styles.page}>
      <PeriodHeader view={shownView} day={day} today={today} onDay={setDay}>
        {!phone && <SegmentedControl label="Вид" value={view} options={VIEWS} onChange={setView} />}
        <FiltersButton />
      </PeriodHeader>
      {isError && (
        <LoadError message="Не удалось загрузить календарь" onRetry={() => void refetch()} />
      )}
      <div className={styles.body}>
        {phone ? (
          <CompactMonth
            day={day}
            today={today}
            items={shown}
            colors={colors}
            timeZone={timeZone}
            onSelectDay={setDay}
          />
        ) : (
          <CalendarGrid
            view={view}
            day={day}
            items={shown}
            colors={colors}
            timeZone={timeZone}
            now={now}
            onSelectDay={setDay}
            onCreateAt={view === "month" ? undefined : (date, time) => create({ day: date, time })}
            onOpenItem={openItem}
          />
        )}
        <DayPanel day={day} items={shown} loaded={loaded} colors={colors} timeZone={timeZone} />
      </div>
      {phone && (
        <Button
          className={styles.fab}
          aria-label="Новое событие"
          icon={<Plus size={26} />}
          onClick={() => create({ day })}
        />
      )}
    </section>
  );
}
