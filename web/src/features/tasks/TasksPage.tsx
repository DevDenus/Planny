import { ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import type { TaskFilters, TaskSummary } from "../../api/client";
import { Button, EmptyState, LoadError, Panel, SegmentedControl, Skeleton, Switch } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { BoardCatalog } from "../boards/BoardCatalog";
import { useBoards } from "../boards/api";
import { useTaskList } from "./api";
import { QuickAdd } from "./QuickAdd";
import { TASK_GROUPS, taskGroup, type TaskGroup } from "./dates";
import { pluralize } from "./labels";
import { TaskRow } from "./TaskRow";
import { useTaskParam, NEW_TASK } from "./taskLinks";
import styles from "./TasksPage.module.css";
import { useNow } from "./useNow";

type Scope = "all" | "personal" | "shared";

const SCOPES: { value: Scope; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "personal", label: "Личные" },
  { value: "shared", label: "Общие" },
];
const PAGE_SIZE = 200;

function LoadingRows() {
  return (
    <div className={styles.loading} aria-label="Загрузка">
      <Skeleton height={52} />
      <Skeleton height={52} />
      <Skeleton height={52} />
    </div>
  );
}

type RowOptions = {
  now: Date;
  timeZone: string;
  /** Boards where this user can only read: their cards can't be ticked from here. */
  readOnlyBoards: ReadonlySet<string>;
};

type GroupProps = RowOptions & {
  title: string;
  tasks: TaskSummary[];
};

function Group({ title, tasks, now, timeZone, readOnlyBoards }: GroupProps) {
  const [open, setOpen] = useState(true);
  if (tasks.length === 0) return null;
  return (
    <Panel className={styles.group}>
      <button
        type="button"
        className={styles.groupHeader}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        <h2 className={styles.groupTitle}>{title}</h2>
        <span className={styles.count}>{tasks.length}</span>
      </button>
      {open && (
        <ul className={styles.rows}>
          {tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              now={now}
              timeZone={timeZone}
              readOnly={readOnlyBoards.has(task.board_id)}
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function DoneGroup({
  filters,
  now,
  timeZone,
  readOnlyBoards,
}: RowOptions & { filters: TaskFilters }) {
  const [open, setOpen] = useState(false);
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useTaskList({ ...filters, status: "done", sort: "updated", limit: PAGE_SIZE }, open);
  const tasks = data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Panel className={styles.group}>
      <button
        type="button"
        className={styles.groupHeader}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        <h2 className={styles.groupTitle}>Выполненные</h2>
      </button>
      {open && isPending && <LoadingRows />}
      {open && isError && (
        <div className={styles.error}>
          <LoadError message="Не удалось загрузить задачи" onRetry={() => void refetch()} />
        </div>
      )}
      {open && !isPending && !isError && tasks.length === 0 && (
        <EmptyState title="Выполненных задач пока нет" />
      )}
      {open && tasks.length > 0 && (
        <ul className={styles.rows}>
          {tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              now={now}
              timeZone={timeZone}
              readOnly={readOnlyBoards.has(task.board_id)}
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

export function TasksPage() {
  const { data: user } = useCurrentUser();
  const { data: boards, isError: boardsFailed, refetch: refetchBoards } = useBoards();
  const { open: openTask } = useTaskParam();
  const [scope, setScope] = useState<Scope>("all");
  const [assignedToMe, setAssignedToMe] = useState(false);
  const now = useNow();

  const filters = useMemo<TaskFilters>(
    () => ({
      ...(scope === "all" ? {} : { scope }),
      ...(assignedToMe ? { assignee: "me" } : {}),
    }),
    [scope, assignedToMe],
  );
  const { data, isPending, isError, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useTaskList({ ...filters, status: "open", sort: "due", limit: PAGE_SIZE });

  const timeZone = user?.timezone ?? "UTC";
  const tasks = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data]);
  const groups = useMemo(() => {
    const byGroup = new Map<TaskGroup, TaskSummary[]>();
    for (const task of tasks) {
      const group = taskGroup(task, now, timeZone);
      byGroup.set(group, [...(byGroup.get(group) ?? []), task]);
    }
    return byGroup;
  }, [tasks, timeZone, now]);

  const personal = boards?.find((board) => board.is_default);
  const target = personal && {
    boardId: personal.id,
    boardName: personal.name,
    // Lists of open cards that aren't narrowed to something a new card doesn't match.
    showsIn: (list: TaskFilters) =>
      list.status === "open" &&
      !list.column_id &&
      !list.board_id &&
      list.assignee === undefined &&
      list.scope !== "shared",
  };
  const readOnlyBoards = useMemo(
    () =>
      new Set(
        (boards ?? []).filter((board) => board.my_role === "viewer").map((board) => board.id),
      ),
    [boards],
  );

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Задачи</h1>
        <SegmentedControl label="Какие задачи" value={scope} options={SCOPES} onChange={setScope} />
        <Switch label="Назначенные мне" checked={assignedToMe} onChange={setAssignedToMe} />
        <Button
          className={styles.newTask}
          icon={<Plus size={18} />}
          onClick={() => openTask(NEW_TASK)}
        >
          Новая задача
        </Button>
      </header>

      <div className={styles.layout}>
        <div className={styles.content}>
          <QuickAdd target={target} />
          {isPending && <LoadingRows />}
          {isError && (
            <div className={styles.error}>
              <LoadError message="Не удалось загрузить задачи" onRetry={() => void refetch()} />
            </div>
          )}
          {!isPending && !isError && tasks.length === 0 && (
            <EmptyState
              title="Задач нет. Добавьте первую"
              action={
                <Button variant="secondary" onClick={() => openTask(NEW_TASK)}>
                  Новая задача
                </Button>
              }
            />
          )}
          {TASK_GROUPS.map((group) => (
            <Group
              key={group.id}
              title={group.title}
              tasks={groups.get(group.id) ?? []}
              now={now}
              timeZone={timeZone}
              readOnlyBoards={readOnlyBoards}
            />
          ))}
          {hasNextPage && (
            <Button
              variant="ghost"
              loading={isFetchingNextPage}
              onClick={() => void fetchNextPage()}
            >
              Показать ещё
            </Button>
          )}
          <DoneGroup
            filters={filters}
            now={now}
            timeZone={timeZone}
            readOnlyBoards={readOnlyBoards}
          />
        </div>

        <aside className={styles.aside}>
          <Panel>
            <h2 className={styles.asideTitle}>Мои доски</h2>
            <BoardCatalog
              boards={boards}
              failed={boardsFailed}
              onRetry={() => void refetchBoards()}
            />
            <p className={styles.total}>
              {tasks.length} {pluralize(tasks.length, "задача", "задачи", "задач")} в работе
            </p>
          </Panel>
        </aside>
      </div>
    </section>
  );
}
