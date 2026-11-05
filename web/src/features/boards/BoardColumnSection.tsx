import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import type { BoardColumn, TaskFilters } from "../../api/client";
import { Button, EmptyState, LoadError, Panel, Skeleton, cx } from "../../ui";
import { useTaskList } from "../tasks/api";
import { NEW_TASK, useTaskParam } from "../tasks/taskLinks";
import { BoardRow } from "./BoardRow";
import styles from "./BoardColumnSection.module.css";
import { useDropColumn } from "./dnd/useDragHandles";

const PAGE_SIZE = 100;

export type BoardColumnSectionProps = {
  column: BoardColumn;
  boardId: string;
  filters: TaskFilters;
  now: Date;
  timeZone: string;
  readOnly: boolean;
};

/** Done columns start folded and load on opening, so a long history doesn't slow the board. */
export function BoardColumnSection({
  column,
  boardId,
  filters,
  now,
  timeZone,
  readOnly,
}: BoardColumnSectionProps) {
  const [open, setOpen] = useState(!column.is_done);
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useTaskList(
      { ...filters, column_id: column.id, status: "all", sort: "position", limit: PAGE_SIZE },
      open,
    );
  const { open: openTask } = useTaskParam();
  const tasks = data?.pages.flatMap((page) => page.items) ?? [];
  const { attach, ...drop } = useDropColumn(column);
  const line = <li className={styles.line} data-drop-line aria-hidden="true" />;

  return (
    <Panel
      ref={attach}
      className={cx(styles.section, drop.targeted && styles.sectionTarget)}
      data-drop-column={column.id}
    >
      <button
        type="button"
        className={styles.header}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        <h2 className={styles.title}>{column.name}</h2>
        <span className={styles.count}>{column.task_count}</span>
      </button>
      {open && isPending && <Skeleton height={52} />}
      {open && isError && (
        <div className={styles.error}>
          <LoadError message="Не удалось загрузить задачи" onRetry={() => void refetch()} />
        </div>
      )}
      {open && !isPending && !isError && tasks.length === 0 && (
        <EmptyState
          title={column.is_done ? "Здесь пока пусто" : "Задач нет. Добавьте первую"}
          action={
            !column.is_done &&
            !readOnly && (
              <Button variant="secondary" onClick={() => openTask(NEW_TASK, boardId, column.id)}>
                Новая задача
              </Button>
            )
          }
        />
      )}
      {open && (tasks.length > 0 || drop.lineAfter === null) && (
        <ul className={styles.rows}>
          {drop.lineAfter === null && line}
          {tasks.map((task) => (
            <Fragment key={task.id}>
              <BoardRow
                task={task}
                now={now}
                timeZone={timeZone}
                showBoard={false}
                readOnly={readOnly}
              />
              {drop.lineAfter === task.id && line}
            </Fragment>
          ))}
        </ul>
      )}
      {open && hasNextPage && (
        <Button variant="ghost" loading={isFetchingNextPage} onClick={() => void fetchNextPage()}>
          Показать ещё
        </Button>
      )}
    </Panel>
  );
}
