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
  cx,
} from "../../ui";
import { useCurrentUser } from "../auth/session";
import { QuickAdd } from "../tasks/QuickAdd";
import { useTaskParam, NEW_TASK } from "../tasks/taskLinks";
import { useNow } from "../tasks/useNow";
import { BoardColumnSection } from "./BoardColumnSection";
import { BoardDialog } from "./BoardDialog";
import { BoardIcon } from "./BoardIcon";
import { useBoard, useColumns, useLabels } from "./api";
import styles from "./BoardPage.module.css";
import { BoardRowPreview } from "./BoardRow";
import { DragLayer } from "./dnd/DragLayer";
import { KanbanBoard } from "./kanban/KanbanBoard";

const NOT_YET = "Появится позже";
type View = "list" | "kanban" | "calendar";
const VIEWS = [
  { value: "list" as const, label: "Список" },
  { value: "kanban" as const, label: "Kanban" },
  { value: "calendar" as const, label: "Календарь", disabled: true, title: NOT_YET },
];
const ALL_MEMBERS = "";
const ALL_LABELS = "";

const viewKey = (boardId: string) => `planny.board-view.${boardId}`;

/** A remembered view is a convenience: storage may be unavailable, and then nothing is lost. */
function rememberedView(boardId: string): View | null {
  try {
    const saved = window.localStorage.getItem(viewKey(boardId));
    return saved === "list" || saved === "kanban" ? saved : null;
  } catch {
    return null;
  }
}

function rememberView(boardId: string, view: View): void {
  try {
    window.localStorage.setItem(viewKey(boardId), view);
  } catch {
    // The view just won't be remembered.
  }
}

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
    showsIn: (list: TaskFilters) => list.column_id === first.id && !list.assignee && !list.label_id,
  };
  return (
    <DragLayer
      boardId={board.id}
      columns={columns}
      stacked
      readOnly={readOnly(board)}
      preview={(drag) => (drag.kind === "card" ? <BoardRowPreview task={drag.task} /> : null)}
    >
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
    </DragLayer>
  );
}

/** Every board gets a screen of its own, so its filters and chosen view don't carry over to another. */
export function BoardPage() {
  const { boardId } = useParams();
  return <BoardScreen key={boardId} boardId={boardId} />;
}

function BoardScreen({ boardId }: { boardId: string | undefined }) {
  const { data: user } = useCurrentUser();
  const { data: board, error, isPending, refetch } = useBoard(boardId);
  const columns = useColumns(boardId);
  const { data: labels } = useLabels(boardId);
  const { open: openTask } = useTaskParam();
  const now = useNow();
  const [editing, setEditing] = useState(false);
  const [assignee, setAssignee] = useState(ALL_MEMBERS);
  const [onlyMine, setOnlyMine] = useState(false);
  const [label, setLabel] = useState(ALL_LABELS);
  const [chosenView, setChosenView] = useState<View | null>(null);

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

  // A value the board doesn't offer any more is not applied. It stays in the state, so it applies
  // again if the board offers it again.
  const activeLabel = labels?.some((item) => item.id === label) ? label : ALL_LABELS;
  const activeAssignee =
    board.is_shared && board.members.some((member) => member.id === assignee)
      ? assignee
      : ALL_MEMBERS;
  const filters: TaskFilters = {
    ...(onlyMine
      ? { assignee: "me" }
      : activeAssignee !== ALL_MEMBERS
        ? { assignee: activeAssignee }
        : {}),
    ...(activeLabel !== ALL_LABELS ? { label_id: activeLabel } : {}),
  };
  const view = chosenView ?? rememberedView(board.id) ?? board.default_view;
  const chooseView = (next: View) => {
    rememberView(board.id, next);
    setChosenView(next);
  };

  return (
    <section className={cx(styles.page, view === "kanban" && styles.pageFull)}>
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
        <SegmentedControl label="Вид доски" value={view} options={VIEWS} onChange={chooseView} />
        {board.is_shared && (
          <SelectField
            hideLabel
            label="Исполнитель"
            className={styles.assignee}
            value={activeAssignee}
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
        {labels && labels.length > 0 && (
          <SelectField
            hideLabel
            label="Метка"
            className={styles.assignee}
            value={activeLabel}
            options={[
              { value: ALL_LABELS, label: "Все метки" },
              ...labels.map((item) => ({ value: item.id, label: item.name })),
            ]}
            onChange={(event) => setLabel(event.target.value)}
          />
        )}
        <Switch label="Только мои" checked={onlyMine} onChange={setOnlyMine} />
      </div>

      {columns.isPending && <Skeleton height={120} />}
      {columns.data && view === "kanban" && (
        <KanbanBoard
          board={board}
          columns={columns.data}
          filters={filters}
          now={now}
          timeZone={user?.timezone ?? "UTC"}
          readOnly={readOnly(board)}
        />
      )}
      {columns.data && view !== "kanban" && (
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
