import { CalendarDays, ListChecks, MessageSquare } from "lucide-react";

import type { TaskSummary } from "../../api/client";
import { Avatar, Checkbox, cx } from "../../ui";
import type { useCardHandle } from "../boards/dnd/useDragHandles";
import { useToggleDone } from "./api";
import { formatDeadline, taskGroup } from "./dates";
import { LabelChip } from "./LabelChip";
import { PRIORITIES } from "./labels";
import styles from "./TaskRow.module.css";
import { useTaskParam } from "./taskLinks";

export type TaskRowProps = {
  task: TaskSummary;
  /** The page's clock, so each row doesn't run a timer of its own. */
  now: Date;
  timeZone: string;
  showBoard?: boolean;
  readOnly?: boolean;
  /** Present where the row can be dragged. */
  drag?: RowDrag;
};

type RowDrag = ReturnType<typeof useCardHandle>;

export function TaskRow({ task, now, timeZone, showBoard = true, readOnly, drag }: TaskRowProps) {
  const { attach, focusTarget, ...handle }: Partial<RowDrag> = drag ?? {};
  const { mutate } = useToggleDone();
  const { open } = useTaskParam();
  const done = task.completed_at !== null;
  const deadline = formatDeadline(task, now, timeZone);
  const overdue = !done && taskGroup(task, now, timeZone) === "overdue";
  const priority = PRIORITIES.find((item) => item.value === task.priority);

  return (
    <li
      ref={attach}
      className={cx(
        styles.row,
        handle.draggable && styles.draggable,
        handle.dragged && !handle.lifted && styles.dragged,
        handle.lifted && styles.lifted,
      )}
      data-card-id={drag ? task.id : undefined}
      data-card-title={drag ? task.title : undefined}
      {...handle.listeners}
    >
      <Checkbox
        hideLabel
        label={done ? `Вернуть в работу: ${task.title}` : `Выполнить: ${task.title}`}
        checked={done}
        disabled={readOnly}
        onChange={(checked) => mutate({ id: task.id, done: checked })}
      />
      <button
        ref={focusTarget}
        type="button"
        className={styles.open}
        onClick={() => open(task.id)}
        {...handle.keys}
      >
        <span className={cx(styles.title, done && styles.titleDone)}>{task.title}</span>
        <span className={styles.meta}>
          {task.labels.map((label) => (
            <LabelChip key={label.id} label={label} />
          ))}
          {priority && (
            <span className={cx(styles.priority, styles[`priority${task.priority}`])}>
              {priority.short}
            </span>
          )}
          {deadline && (
            <span className={cx(styles.chip, overdue && styles.overdue)}>
              <CalendarDays size={14} aria-hidden="true" />
              {deadline}
            </span>
          )}
          {showBoard && <span className={styles.chip}>{task.board_name}</span>}
          {task.checklist_total > 0 && (
            <span className={styles.chip}>
              <ListChecks size={14} aria-hidden="true" />
              {task.checklist_done}/{task.checklist_total}
            </span>
          )}
          {task.comments_count > 0 && (
            <span
              className={styles.chip}
              role="img"
              aria-label={`Комментариев: ${task.comments_count}`}
            >
              <MessageSquare size={14} aria-hidden="true" />
              {task.comments_count}
            </span>
          )}
        </span>
      </button>
      {task.assignees.length > 0 && (
        <span className={styles.assignees}>
          {task.assignees.map((user) => (
            <Avatar key={user.id} name={user.display_name} color={user.color} size={26} />
          ))}
        </span>
      )}
    </li>
  );
}
