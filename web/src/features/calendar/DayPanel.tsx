import { Plus } from "lucide-react";

import type { CalendarItem, CategoryColor } from "../../api/client";
import { Button, Panel } from "../../ui";
import { DeadlineRow, EventRow } from "./CalendarRows";
import rowStyles from "./CalendarRows.module.css";
import styles from "./DayPanel.module.css";
import { useEventParam } from "./eventLinks";
import { itemsOfDay } from "./items";
import { dayTitle } from "./period";

export type DayPanelProps = {
  day: string;
  items: CalendarItem[];
  colors: Map<string, CategoryColor>;
  timeZone: string;
  /** The calendar of a board has no events, and nothing is created from it. */
  tasksOnly?: boolean;
};

export function DayPanel({ day, items, colors, timeZone, tasksOnly }: DayPanelProps) {
  const { create } = useEventParam();
  const { events, tasks } = itemsOfDay(items, day, timeZone);
  return (
    <Panel className={styles.panel}>
      <h2 className={styles.title}>{dayTitle(day)}</h2>
      {!tasksOnly && (
        <section className={styles.section}>
          <h3 className={styles.heading}>
            События <span className={styles.count}>{events.length}</span>
          </h3>
          {events.length > 0 && (
            <ul className={rowStyles.list}>
              {events.map((event) => (
                <EventRow
                  key={`${event.event_id}-${event.occurrence_start}`}
                  event={event}
                  color={event.category_id ? colors.get(event.category_id) : undefined}
                  timeZone={timeZone}
                />
              ))}
            </ul>
          )}
        </section>
      )}
      <section className={styles.section}>
        <h3 className={styles.heading}>
          Задачи <span className={styles.count}>{tasks.length}</span>
        </h3>
        {tasks.length > 0 && (
          <ul className={rowStyles.list}>
            {tasks.map((task) => (
              <DeadlineRow key={task.task_id} task={task} />
            ))}
          </ul>
        )}
      </section>
      {!tasksOnly && (
        <Button className={styles.create} icon={<Plus size={20} />} onClick={() => create({ day })}>
          Новое событие
        </Button>
      )}
    </Panel>
  );
}
