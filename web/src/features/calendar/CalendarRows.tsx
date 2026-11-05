import { Users } from "lucide-react";

import type { CategoryColor, EventOccurrence, TaskDeadline } from "../../api/client";
import { Avatar, Checkbox, cx } from "../../ui";
import { useBoards } from "../boards/api";
import { PRIORITIES } from "../tasks/labels";
import { useTaskParam } from "../tasks/taskLinks";
import { useToggleDeadline } from "./api";
import { useEventParam } from "./eventLinks";
import { eventTime } from "./items";
import styles from "./CalendarRows.module.css";

type EventRowProps = {
  event: EventOccurrence;
  color: CategoryColor | undefined;
  timeZone: string;
};

export function EventRow({ event, color, timeZone }: EventRowProps) {
  const { open } = useEventParam();
  const shared = event.participants.length > 1;
  return (
    <li>
      <button
        type="button"
        className={cx(styles.row, styles.event)}
        style={{ "--item": `var(--cat-${color ?? "none"}, var(--border-strong))` } as object}
        onClick={() => open(event.event_id)}
      >
        <span className={styles.text}>
          <span className={styles.title}>
            {shared && <Users size={15} aria-hidden="true" />}
            {event.title}
          </span>
          <span className={styles.meta}>{eventTime(event, timeZone)}</span>
        </span>
        {shared && (
          <span className={styles.people}>
            {event.participants.map((person) => (
              <Avatar key={person.id} name={person.display_name} color={person.color} size={26} />
            ))}
          </span>
        )}
      </button>
    </li>
  );
}

export function DeadlineRow({ task }: { task: TaskDeadline }) {
  const { mutate } = useToggleDeadline();
  const { open } = useTaskParam();
  const { data: boards } = useBoards();
  const done = task.completed_at !== null;
  const priority = PRIORITIES.find((item) => item.value === task.priority);
  const writable =
    boards?.some(
      (board) =>
        board.id === task.board_id && board.my_role !== "viewer" && board.archived_at === null,
    ) ?? false;
  return (
    <li className={styles.row}>
      <Checkbox
        hideLabel
        label={done ? `Вернуть в работу: ${task.title}` : `Выполнить: ${task.title}`}
        checked={done}
        disabled={!writable}
        onChange={(checked) => mutate({ id: task.task_id, done: checked })}
      />
      <button type="button" className={styles.open} onClick={() => open(task.task_id)}>
        <span className={styles.text}>
          <span className={cx(styles.title, done && styles.done)}>{task.title}</span>
          <span className={styles.meta}>{task.board_name}</span>
        </span>
        {priority && (
          <span className={cx(styles.priority, styles[`priority${task.priority}`])}>
            {priority.short}
          </span>
        )}
      </button>
    </li>
  );
}
