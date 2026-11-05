import type { CalendarItem, CategoryColor } from "../../api/client";
import { cx } from "../../ui";
import styles from "./CompactMonth.module.css";
import { onDay } from "./items";
import { dayNumber, dayTitle, monthGrid, sameMonth } from "./period";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MAX_DOTS = 3;

export type CompactMonthProps = {
  day: string;
  today: string;
  items: CalendarItem[];
  colors: Map<string, CategoryColor>;
  timeZone: string;
  onSelectDay: (day: string) => void;
};

function dotColor(item: CalendarItem, colors: Map<string, CategoryColor>): string {
  if (item.type === "task") return `var(--priority-${item.priority})`;
  const color = item.category_id ? colors.get(item.category_id) : undefined;
  return color ? `var(--cat-${color})` : "var(--text-muted)";
}

/** The month of a phone: a date under which dots say that something is there. */
export function CompactMonth({
  day,
  today,
  items,
  colors,
  timeZone,
  onSelectDay,
}: CompactMonthProps) {
  return (
    <div className={styles.month}>
      {WEEKDAYS.map((name) => (
        <span key={name} className={styles.weekday}>
          {name}
        </span>
      ))}
      {monthGrid(day).map((cell) => {
        const dots = items.filter((item) => onDay(item, cell, timeZone)).slice(0, MAX_DOTS);
        return (
          <button
            key={cell}
            type="button"
            aria-label={dayTitle(cell)}
            aria-pressed={cell === day}
            className={cx(
              styles.day,
              cell === day && styles.selected,
              cell === today && styles.today,
              !sameMonth(cell, day) && styles.outside,
            )}
            onClick={() => onSelectDay(cell)}
          >
            <span className={styles.number}>{dayNumber(cell)}</span>
            <span className={styles.dots}>
              {dots.map((item) => (
                <span
                  key={
                    item.type === "task"
                      ? item.task_id
                      : `${item.event_id}-${item.occurrence_start}`
                  }
                  className={styles.dot}
                  style={{ background: dotColor(item, colors) }}
                />
              ))}
            </span>
          </button>
        );
      })}
    </div>
  );
}
