import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import type { BoardColumn, TaskFilters } from "../../api/client";
import { Banner, Button, EmptyState, Panel, Skeleton } from "../../ui";
import { useTaskList } from "../tasks/api";
import { TaskRow } from "../tasks/TaskRow";
import styles from "./BoardColumnSection.module.css";

const PAGE_SIZE = 100;

export type BoardColumnSectionProps = {
  column: BoardColumn;
  filters: TaskFilters;
  now: Date;
  timeZone: string;
  readOnly: boolean;
};

/** Done columns start folded and load on opening, so a long history doesn't slow the board. */
export function BoardColumnSection({
  column,
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
  const tasks = data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Panel className={styles.section}>
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
          <Banner tone="error">Не удалось загрузить задачи</Banner>
          <Button variant="secondary" onClick={() => void refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {open && !isPending && !isError && tasks.length === 0 && (
        <EmptyState title={column.is_done ? "Здесь пока пусто" : "Задач нет. Добавьте первую"} />
      )}
      {open && tasks.length > 0 && (
        <ul className={styles.rows}>
          {tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              now={now}
              timeZone={timeZone}
              showBoard={false}
              readOnly={readOnly}
            />
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
