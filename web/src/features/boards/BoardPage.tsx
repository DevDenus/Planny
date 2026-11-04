import { Lock, Plus, Settings } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, type Board, type BoardColumn, type TaskFilters } from "../../api/client";
import {
  Avatar,
  Banner,
  Button,
  EmptyState,
  IconButton,
  Panel,
  SegmentedControl,
  SelectField,
  Skeleton,
  Switch,
} from "../../ui";
import { useCurrentUser } from "../auth/session";
import { QuickAdd } from "../tasks/QuickAdd";
import { useTaskParam, NEW_TASK } from "../tasks/taskLinks";
import { useNow } from "../tasks/useNow";
import { BoardColumnSection } from "./BoardColumnSection";
import { BoardDialog } from "./BoardDialog";
import { BoardIcon } from "./BoardIcon";
import { useBoard, useColumns } from "./api";
import styles from "./BoardPage.module.css";

const NOT_YET = "Появится позже";
const VIEWS = [
  { value: "list" as const, label: "Список" },
  { value: "kanban" as const, label: "Kanban", disabled: true, title: NOT_YET },
  { value: "calendar" as const, label: "Календарь", disabled: true, title: NOT_YET },
];
const ALL_MEMBERS = "";

function readOnly(board: Board): boolean {
  return board.my_role === "viewer" || board.archived_at !== null;
}

function BoardList({
  board,
  columns,
  filters,
  now,
  timeZone,
}: {
  board: Board;
  columns: BoardColumn[];
  filters: TaskFilters;
  now: Date;
  timeZone: string;
}) {
  const first = columns.find((column) => !column.is_done);
  const target = first && {
    boardId: board.id,
    boardName: board.name,
    columnId: first.id,
    showsIn: (list: TaskFilters) => list.column_id === first.id && !list.assignee,
  };
  return (
    <div className={styles.list}>
      {!readOnly(board) && <QuickAdd target={target} placeholder="Быстро добавить" />}
      {columns.map((column) => (
        <BoardColumnSection
          key={column.id}
          column={column}
          filters={filters}
          now={now}
          timeZone={timeZone}
          readOnly={readOnly(board)}
        />
      ))}
    </div>
  );
}

export function BoardPage() {
  const { boardId } = useParams();
  const { data: user } = useCurrentUser();
  const { data: board, error, isPending, refetch } = useBoard(boardId);
  const columns = useColumns(boardId);
  const { open: openTask } = useTaskParam();
  const now = useNow();
  const [editing, setEditing] = useState(false);
  const [assignee, setAssignee] = useState(ALL_MEMBERS);
  const [onlyMine, setOnlyMine] = useState(false);

  if (isPending) return <Skeleton height={120} />;
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title="Объект больше не существует"
        action={
          <Link to="/boards">
            <Button variant="secondary">К доскам</Button>
          </Link>
        }
      />
    );
  }
  if (!board) {
    return (
      <Panel className={styles.error}>
        <Banner tone="error">Не удалось загрузить доску</Banner>
        <Button variant="secondary" onClick={() => void refetch()}>
          Повторить
        </Button>
      </Panel>
    );
  }

  const filters: TaskFilters = onlyMine
    ? { assignee: "me" }
    : assignee !== ALL_MEMBERS
      ? { assignee }
      : {};

  return (
    <section className={styles.page}>
      <header className={styles.header}>
        <span className={styles.icon}>
          <BoardIcon icon={board.icon} size={26} />
        </span>
        <h1 className={styles.title}>{board.name}</h1>
        {readOnly(board) && (
          <span className={styles.readOnly}>
            <Lock size={14} aria-hidden="true" />
            Только чтение
          </span>
        )}
        {board.is_shared && (
          <span className={styles.members}>
            {board.members.map((member) => (
              <Avatar key={member.id} name={member.display_name} color={member.color} size={28} />
            ))}
          </span>
        )}
        <div className={styles.actions}>
          {!readOnly(board) && (
            <Button
              className={styles.newTask}
              icon={<Plus size={18} />}
              onClick={() => openTask(NEW_TASK, board.id)}
            >
              Новая задача
            </Button>
          )}
          <IconButton label="Настройки доски" onClick={() => setEditing(true)}>
            <Settings size={20} />
          </IconButton>
        </div>
      </header>

      <div className={styles.filters}>
        <SegmentedControl label="Вид доски" value="list" options={VIEWS} onChange={() => {}} />
        {board.is_shared && (
          <SelectField
            hideLabel
            label="Исполнитель"
            className={styles.assignee}
            value={assignee}
            disabled={onlyMine}
            options={[
              { value: ALL_MEMBERS, label: "Все исполнители" },
              ...board.members.map((member) => ({
                value: member.id,
                label: member.display_name,
              })),
            ]}
            onChange={(event) => setAssignee(event.target.value)}
          />
        )}
        <Switch label="Только мои" checked={onlyMine} onChange={setOnlyMine} />
      </div>

      {columns.isPending && <Skeleton height={120} />}
      {columns.data && (
        <BoardList
          board={board}
          columns={columns.data}
          filters={filters}
          now={now}
          timeZone={user?.timezone ?? "UTC"}
        />
      )}

      {editing && <BoardDialog board={board} onClose={() => setEditing(false)} />}
    </section>
  );
}
