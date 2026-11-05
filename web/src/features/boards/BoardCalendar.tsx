import { useMemo, useState } from "react";

import type { Board, CalendarItem, TaskFilters } from "../../api/client";
import { Banner } from "../../ui";
import { useCalendarItems } from "../calendar/api";
import { CalendarGrid } from "../calendar/CalendarGrid";
import { CompactMonth } from "../calendar/CompactMonth";
import { DayPanel } from "../calendar/DayPanel";
import { PeriodHeader } from "../calendar/PeriodHeader";
import { viewRange } from "../calendar/period";
import { useIsPhone } from "../calendar/useIsPhone";
import { fromLocalInput, localDate } from "../tasks/dates";
import { useTaskParam } from "../tasks/taskLinks";
import styles from "./BoardCalendar.module.css";

export type BoardCalendarProps = {
  board: Board;
  filters: TaskFilters;
  now: Date;
  timeZone: string;
};

const NO_COLORS = new Map();

/**
 * All deadlines of the board, whoever does them, until the filters narrow them: an overview of the
 * board, not of a person.
 */
export function BoardCalendar({ board, filters, now, timeZone }: BoardCalendarProps) {
  const today = localDate(now, timeZone);
  const [chosenDay, setDay] = useState<string | null>(null);
  const day = chosenDay ?? today;
  const phone = useIsPhone();
  const { open } = useTaskParam();
  const { first, end } = viewRange("month", day);
  const { data, isError } = useCalendarItems(
    {
      from: fromLocalInput(first, "00:00", timeZone),
      to: fromLocalInput(end, "00:00", timeZone),
    },
    board.id,
    filters,
  );
  const items = useMemo<CalendarItem[]>(() => data ?? [], [data]);

  return (
    <div className={styles.calendar}>
      <PeriodHeader view="month" day={day} today={today} onDay={setDay} />
      {isError && <Banner tone="error">Не удалось загрузить календарь</Banner>}
      {phone ? (
        <>
          <CompactMonth
            day={day}
            today={today}
            items={items}
            colors={NO_COLORS}
            timeZone={timeZone}
            onSelectDay={setDay}
          />
          <DayPanel day={day} items={items} colors={NO_COLORS} timeZone={timeZone} tasksOnly />
        </>
      ) : (
        <div className={styles.grid}>
          <CalendarGrid
            view="month"
            day={day}
            items={items}
            colors={NO_COLORS}
            timeZone={timeZone}
            now={now}
            onSelectDay={setDay}
            onOpenItem={(item) => {
              if (item.type === "task") open(item.task_id);
            }}
          />
        </div>
      )}
    </div>
  );
}
