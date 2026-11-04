import { Plus } from "lucide-react";
import { Fragment, useState } from "react";

import type { Board, BoardColumn, TaskFilters } from "../../../api/client";
import { Banner, Button, Menu, Skeleton, cx, type MenuProps } from "../../../ui";
import { useTaskList } from "../../tasks/api";
import { QuickAdd } from "../../tasks/QuickAdd";
import { useMoveColumn, useUpdateColumn } from "../api";
import { useDragLayer } from "../dnd/dragContext";
import { useColumnHandle, useDropColumn } from "../dnd/useDragHandles";
import { DeleteColumnDialog, DoneColumnDialog, RenameColumnDialog } from "./ColumnDialogs";
import styles from "./Kanban.module.css";
import { KanbanCard } from "./KanbanCard";

const PAGE_SIZE = 100;

export function CardDropLine() {
  return <li className={styles.line} data-drop-line aria-hidden="true" />;
}

type ColumnMenuProps = {
  board: Board;
  column: BoardColumn;
  columns: BoardColumn[];
  onDialog: (dialog: Dialog) => void;
};

type Dialog = "rename" | "done" | "delete";

function ColumnMenu({ board, column, columns, onDialog }: ColumnMenuProps) {
  const move = useMoveColumn(board.id);
  const update = useUpdateColumn(board.id);
  const index = columns.findIndex((item) => item.id === column.id);
  const onlyOfKind = !columns.some(
    (item) => item.id !== column.id && item.is_done === column.is_done,
  );
  const kindHint = column.is_done
    ? "Это последняя завершающая колонка"
    : "Это последняя незавершающая колонка";

  const items: MenuProps["items"] = [
    { label: "Переименовать", onSelect: () => onDialog("rename") },
    {
      label: column.is_done ? "Снять отметку завершающей" : "Отметить как завершающую",
      disabled: onlyOfKind,
      hint: onlyOfKind ? kindHint : undefined,
      onSelect: () => {
        // With nothing on the column there is nobody to warn about.
        if (column.task_count > 0) onDialog("done");
        else update.mutate({ columnId: column.id, body: { is_done: !column.is_done } });
      },
    },
    {
      label: "Переместить влево",
      disabled: index === 0,
      onSelect: () =>
        move.mutate({
          columnId: column.id,
          afterId: index > 1 ? (columns[index - 2]?.id ?? null) : null,
        }),
    },
    {
      label: "Переместить вправо",
      disabled: index === columns.length - 1,
      onSelect: () => move.mutate({ columnId: column.id, afterId: columns[index + 1]?.id ?? null }),
    },
    {
      label: "Удалить",
      danger: true,
      disabled: onlyOfKind,
      hint: onlyOfKind ? kindHint : undefined,
      onSelect: () => onDialog("delete"),
    },
  ];
  return <Menu label={`Меню колонки: ${column.name}`} items={items} />;
}

export type KanbanColumnProps = {
  board: Board;
  column: BoardColumn;
  columns: BoardColumn[];
  filters: TaskFilters;
  now: Date;
  timeZone: string;
};

export function KanbanColumn({
  board,
  column,
  columns,
  filters,
  now,
  timeZone,
}: KanbanColumnProps) {
  const { readOnly } = useDragLayer();
  const { attach: attachList, ...drop } = useDropColumn(column);
  const { attach: attachHeader, focusTarget, ...handle } = useColumnHandle(column);
  const [adding, setAdding] = useState(false);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useTaskList({
      ...filters,
      column_id: column.id,
      status: "all",
      sort: "position",
      limit: PAGE_SIZE,
    });
  const tasks = data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = Object.keys(filters).length > 0;
  const closeDialog = () => setDialog(null);

  return (
    <section
      className={cx(
        styles.column,
        column.is_done && styles.columnDone,
        drop.targeted && styles.columnTarget,
        handle.dragged && styles.columnLifted,
      )}
      aria-label={column.name}
      data-drop-column={column.id}
    >
      <header ref={attachHeader} className={styles.columnHeader} {...handle.listeners}>
        <h2
          ref={focusTarget}
          className={styles.columnTitle}
          tabIndex={readOnly ? undefined : 0}
          {...handle.keys}
        >
          {column.name}
        </h2>
        <span className={styles.count}>{filtered ? tasks.length : column.task_count}</span>
        {!readOnly && (
          <ColumnMenu board={board} column={column} columns={columns} onDialog={setDialog} />
        )}
      </header>

      <ul ref={attachList} className={styles.cards}>
        {drop.lineAfter === null && <CardDropLine />}
        {tasks.map((task) => (
          <Fragment key={task.id}>
            <KanbanCard task={task} now={now} timeZone={timeZone} />
            {drop.lineAfter === task.id && <CardDropLine />}
          </Fragment>
        ))}
        {isPending && (
          <li>
            <Skeleton height={72} />
          </li>
        )}
        {isError && (
          <li className={styles.columnError}>
            <Banner tone="error">Не удалось загрузить задачи</Banner>
            <Button variant="secondary" onClick={() => void refetch()}>
              Повторить
            </Button>
          </li>
        )}
        {!isPending && !isError && tasks.length === 0 && (
          <li className={styles.empty}>{readOnly ? "Карточек нет" : "Перетащите карточку сюда"}</li>
        )}
      </ul>

      {hasNextPage && (
        <Button variant="ghost" loading={isFetchingNextPage} onClick={() => void fetchNextPage()}>
          Показать ещё
        </Button>
      )}
      {!readOnly &&
        (adding ? (
          <QuickAdd
            placeholder="Название задачи"
            target={{
              boardId: board.id,
              boardName: board.name,
              columnId: column.id,
              showsIn: (list) => list.column_id === column.id && !list.assignee && !list.label_id,
            }}
          />
        ) : (
          <Button variant="ghost" icon={<Plus size={18} />} onClick={() => setAdding(true)}>
            Добавить задачу
          </Button>
        ))}

      {dialog === "rename" && (
        <RenameColumnDialog boardId={board.id} column={column} onClose={closeDialog} />
      )}
      {dialog === "done" && (
        <DoneColumnDialog boardId={board.id} column={column} onClose={closeDialog} />
      )}
      {dialog === "delete" && (
        <DeleteColumnDialog
          boardId={board.id}
          column={column}
          columns={columns}
          onClose={closeDialog}
        />
      )}
    </section>
  );
}
