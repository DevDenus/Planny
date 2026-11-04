import { CalendarDays, CheckCircle2, ListChecks, MessageSquare } from "lucide-react";
import { useState } from "react";

import type { TaskSummary } from "../../../api/client";
import { Avatar, Menu, cx } from "../../../ui";
import { formatDeadline, taskGroup } from "../../tasks/dates";
import { LabelChip } from "../../tasks/LabelChip";
import { PRIORITIES } from "../../tasks/labels";
import { useTaskParam } from "../../tasks/taskLinks";
import { useCardHandle } from "../dnd/useDragHandles";
import styles from "./Kanban.module.css";
import { MoveCardDialog } from "./MoveCardDialog";

type CardBodyProps = {
  task: TaskSummary;
  now: Date;
  timeZone: string;
};

function CardBody({ task, now, timeZone }: CardBodyProps) {
  const done = task.completed_at !== null;
  const deadline = formatDeadline(task, now, timeZone);
  const overdue = !done && taskGroup(task, now, timeZone) === "overdue";
  const priority = PRIORITIES.find((item) => item.value === task.priority);

  return (
    <>
      {task.labels.length > 0 && (
        <span className={styles.labels}>
          {task.labels.map((label) => (
            <LabelChip key={label.id} label={label} />
          ))}
        </span>
      )}
      <span className={cx(styles.cardTitle, done && styles.cardDone)}>
        {done && (
          <CheckCircle2 size={16} className={styles.doneMark} aria-label="Выполнено" role="img" />
        )}
        {task.title}
      </span>
      <span className={styles.meta}>
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
        {task.checklist_total > 0 && (
          <span className={styles.chip}>
            <ListChecks size={14} aria-hidden="true" />
            {task.checklist_done}/{task.checklist_total}
          </span>
        )}
        {task.comments_count > 0 && (
          <span className={styles.chip} aria-label={`Комментариев: ${task.comments_count}`}>
            <MessageSquare size={14} aria-hidden="true" />
            {task.comments_count}
          </span>
        )}
        {task.assignees.length > 0 && (
          <span className={styles.assignees}>
            {task.assignees.map((user) => (
              <Avatar key={user.id} name={user.display_name} color={user.color} size={24} />
            ))}
          </span>
        )}
      </span>
    </>
  );
}

/** The copy under the pointer. */
export function CardPreview(props: CardBodyProps) {
  return (
    <div className={cx(styles.card, styles.preview)}>
      <span className={styles.open}>
        <CardBody {...props} />
      </span>
    </div>
  );
}

export function KanbanCard({ task, now, timeZone }: CardBodyProps) {
  const { open } = useTaskParam();
  const [moving, setMoving] = useState(false);
  const { attach, focusTarget, ...handle } = useCardHandle(task);

  // The dialog stays out of the card: events from a portal still bubble through React, and a
  // press inside it would start dragging the card.
  return (
    <>
      <li
        ref={attach}
        className={cx(
          styles.card,
          handle.dragged && !handle.lifted && styles.placeholder,
          handle.lifted && styles.lifted,
        )}
        data-card-id={task.id}
        data-card-title={task.title}
        {...handle.listeners}
      >
        <button
          ref={focusTarget}
          type="button"
          className={styles.open}
          onClick={() => open(task.id)}
          {...handle.keys}
        >
          <CardBody task={task} now={now} timeZone={timeZone} />
        </button>
        {handle.draggable && (
          <Menu
            label={`Меню карточки: ${task.title}`}
            className={styles.cardMenu}
            items={[{ label: "Переместить в…", onSelect: () => setMoving(true) }]}
          />
        )}
      </li>
      {moving && <MoveCardDialog task={task} onClose={() => setMoving(false)} />}
    </>
  );
}
