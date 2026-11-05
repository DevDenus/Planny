import { useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, type Task, type TaskCreate, type TaskUpdate } from "../../api/client";
import { TASKS_KEY } from "../../api/queryClient";
import {
  Avatar,
  Banner,
  Button,
  Checkbox,
  ConflictDialog,
  Dialog,
  EmptyState,
  LoadError,
  SelectField,
  Skeleton,
  TextArea,
  TextField,
  useFocusInvalid,
} from "../../ui";
import { useCurrentUser } from "../auth/session";
import { useBoard, useBoards, useColumns, useLabels, useMembers } from "../boards/api";
import { TaskEventLinks } from "../calendar/TaskEventLinks";
import {
  failureMessage,
  useCreateTask,
  useDeleteTask,
  useMoveTask,
  useTask,
  useUpdateTask,
} from "./api";
import { addDays, formatMoment, fromLocalInput, toLocalInput } from "./dates";
import { LabelPicker } from "./LabelPicker";
import { PRIORITIES } from "./labels";
import { DraftChecklist, TaskChecklist } from "./TaskChecklist";
import styles from "./TaskDialog.module.css";
import { TaskFeed } from "./TaskFeed";
import { NEW_TASK, useTaskParam } from "./taskLinks";

const TITLE_MAX_LENGTH = 200;
const PRIORITY_OPTIONS = PRIORITIES.map(({ value, label }) => ({ value: String(value), label }));

type Draft = {
  title: string;
  boardId: string;
  columnId: string;
  description: string;
  priority: string;
  startDate: string;
  dueDate: string;
  dueTime: string;
  reminderDate: string;
  reminderTime: string;
  assigneeIds: string[];
  labelIds: string[];
};

type FieldErrors = { title?: string; startDate?: string; dueDate?: string; reminder?: string };

type Conflict = {
  version: number;
  lastChange?: string;
};

type LastChange = { actor: { display_name: string }; at: string };

function draftOf(task: Task, timeZone: string): Draft {
  const due = task.due_at
    ? toLocalInput(task.due_at, timeZone)
    : { date: task.due_date ?? "", time: "" };
  const reminder = toLocalInput(task.reminder_at, timeZone);
  return {
    title: task.title,
    boardId: task.board_id,
    columnId: task.column_id,
    description: task.description ?? "",
    priority: String(task.priority),
    startDate: task.start_date ?? "",
    dueDate: due.date,
    dueTime: due.time,
    reminderDate: reminder.date,
    reminderTime: reminder.time,
    assigneeIds: task.assignees.map((user) => user.id),
    labelIds: task.labels.map((label) => label.id),
  };
}

function deadline(
  draft: Draft,
  timeZone: string,
): { due_date: string | null; due_at: string | null } {
  if (draft.dueDate && draft.dueTime) {
    return { due_date: null, due_at: fromLocalInput(draft.dueDate, draft.dueTime, timeZone) };
  }
  return { due_date: draft.dueDate || null, due_at: null };
}

/** The personal reminder as an instant. Without both a day and a time there is no reminder. */
function reminderAt(draft: Draft, timeZone: string): string | null {
  if (draft.reminderDate && draft.reminderTime) {
    return fromLocalInput(draft.reminderDate, draft.reminderTime, timeZone);
  }
  return null;
}

function sameIds(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((id) => right.includes(id));
}

function changes(before: Draft, draft: Draft, timeZone: string): Omit<TaskUpdate, "version"> {
  return {
    ...(draft.title.trim() !== before.title && { title: draft.title.trim() }),
    ...(draft.description !== before.description && {
      description: draft.description.trim() || null,
    }),
    ...(draft.priority !== before.priority && { priority: Number(draft.priority) }),
    ...(draft.startDate !== before.startDate && { start_date: draft.startDate || null }),
    ...((draft.dueDate !== before.dueDate || draft.dueTime !== before.dueTime) &&
      deadline(draft, timeZone)),
    ...((draft.reminderDate !== before.reminderDate ||
      draft.reminderTime !== before.reminderTime) && {
      reminder_at: reminderAt(draft, timeZone),
    }),
    ...(!sameIds(draft.assigneeIds, before.assigneeIds) && { assignee_ids: draft.assigneeIds }),
    ...(!sameIds(draft.labelIds, before.labelIds) && { label_ids: draft.labelIds }),
  };
}

function validate(draft: Draft): FieldErrors {
  const errors: FieldErrors = {};
  if (!draft.title.trim()) errors.title = "Введите название";
  if (draft.dueTime && !draft.dueDate) errors.dueDate = "Укажите дату";
  if (Boolean(draft.reminderDate) !== Boolean(draft.reminderTime)) {
    errors.reminder = "Укажите дату и время";
  }
  if (draft.startDate && draft.dueDate && draft.startDate > draft.dueDate) {
    errors.startDate = "Не позже дедлайна";
  }
  return errors;
}

function createBody(draft: Draft, checklist: string[], timeZone: string, id: string): TaskCreate {
  return {
    id,
    board_id: draft.boardId,
    column_id: draft.columnId || null,
    title: draft.title.trim(),
    description: draft.description.trim() || null,
    priority: Number(draft.priority),
    start_date: draft.startDate || null,
    ...deadline(draft, timeZone),
    reminder_at: reminderAt(draft, timeZone),
    assignee_ids: draft.assigneeIds,
    label_ids: draft.labelIds,
    checklist,
  };
}

type TaskFormProps = {
  /** Without a task the form creates one. */
  task?: Task;
  initial: Draft;
  timeZone: string;
  /** The task is gone on the server while the last copy stays on screen. */
  removed?: boolean;
  onClose: () => void;
  onReload: () => void;
};

function TaskForm({ task, initial, timeZone, removed, onClose, onReload }: TaskFormProps) {
  const create = useCreateTask();
  const update = useUpdateTask();
  const move = useMoveTask();
  const remove = useDeleteTask();
  const { data: boards } = useBoards();
  // The state the user started from. The task keeps refreshing underneath the open form, and
  // comparing with that would send someone else's change back as an edit of this user.
  const [base] = useState(initial);
  const [version] = useState(task?.version ?? 1);
  // One id for the life of the form, so a retry after a lost response can't create a second task.
  const [newId] = useState(() => crypto.randomUUID());
  const [draft, setDraft] = useState(initial);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [checklist, setChecklist] = useState<string[]>([]);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [failure, setFailure] = useState<string>();
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [gone, setGone] = useState(false);
  const [saving, setSaving] = useState(false);
  const form = useFocusInvalid(errors);

  const { data: board } = useBoard(draft.boardId);
  const { data: columns, isError: noColumns, refetch: reloadColumns } = useColumns(draft.boardId);
  const { data: members } = useMembers(draft.boardId);
  const { data: labels } = useLabels(draft.boardId);
  const readOnly =
    board !== undefined && (board.my_role === "viewer" || board.archived_at !== null);

  const writableBoards = (boards ?? []).filter((item) => item.my_role !== "viewer");
  const firstOpen = columns?.find((column) => !column.is_done)?.id;
  // A card leaving its board needs a place on the new one, and its columns may still be loading.
  const noPlace = Boolean(task) && draft.boardId !== base.boardId && !draft.columnId && !firstOpen;
  const set = (change: Partial<Draft>) => setDraft((current) => ({ ...current, ...change }));

  // Someone may have removed a label or a member while the form stood open, or the card was
  // given another board. What is no longer there can't be sent.
  const current = (): Draft => ({
    ...draft,
    labelIds: labels
      ? draft.labelIds.filter((id) => labels.some((label) => label.id === id))
      : draft.labelIds,
    assigneeIds: members
      ? draft.assigneeIds.filter((id) => members.some(({ user }) => user.id === id))
      : draft.assigneeIds,
  });

  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.code === "version_conflict") {
      const { current, last_change: last } = error.details as {
        current: Task;
        last_change: LastChange | null;
      };
      setConflict({
        version: current.version,
        lastChange: last
          ? `${last.actor.display_name}, ${formatMoment(last.at, new Date(), timeZone)}`
          : undefined,
      });
    } else if (error instanceof ApiError && error.status === 404 && task) {
      setGone(true);
    } else if (error instanceof ApiError && error.fields.start_date) {
      setErrors({ startDate: error.fields.start_date });
    } else {
      setFailure(failureMessage(error));
    }
  };

  const save = async (expected: number) => {
    setFailure(undefined);
    setSaving(true);
    try {
      const wanted = current();
      if (!task) {
        await create.mutateAsync(createBody(wanted, checklist, timeZone, newId));
      } else {
        const edited = changes(base, wanted, timeZone);
        const body = Object.keys(edited).length > 0 ? { ...edited, version: expected } : undefined;
        // A new board without a chosen column means the first open one, as for a new task.
        const columnId = wanted.columnId || firstOpen || base.columnId;
        if (columnId !== base.columnId) {
          await move.mutateAsync({ id: task.id, columnId, afterId: null, changes: body });
        } else if (body) {
          await update.mutateAsync({ id: task.id, body });
        }
      }
      onClose();
    } catch (error) {
      fail(error);
    } finally {
      setSaving(false);
    }
  };

  const recreate = async () => {
    setSaving(true);
    try {
      // Check marks stay behind: POST /tasks takes the texts only.
      const items = task ? task.checklist.map((item) => item.text) : checklist;
      await create.mutateAsync(createBody(current(), items, timeZone, newId));
      onClose();
    } catch (error) {
      setFailure(failureMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found = validate(draft);
    setErrors(found);
    if (Object.keys(found).length === 0) void save(version);
  };

  const footer = (
    <>
      {task && !readOnly && (
        <Button
          variant="danger"
          className={styles.delete}
          icon={<Trash2 size={18} />}
          onClick={() => setConfirmingDelete(true)}
        >
          Удалить
        </Button>
      )}
      <Button variant="secondary" className={styles.cancel} onClick={onClose}>
        {readOnly ? "Закрыть" : "Отмена"}
      </Button>
      {!readOnly && (
        <Button type="submit" form="task-form" loading={saving} disabled={noPlace}>
          Сохранить
        </Button>
      )}
    </>
  );

  return (
    <Dialog
      title={task ? "Задача" : "Новая задача"}
      width={task ? 980 : 640}
      onClose={onClose}
      footer={footer}
    >
      <div className={task ? styles.columns : undefined}>
        <div className={styles.fields}>
          <form id="task-form" ref={form} className={styles.form} onSubmit={submit} noValidate>
            {readOnly && <Banner tone="info">Доска доступна только для чтения</Banner>}
            {failure && <Banner tone="error">{failure}</Banner>}
            {(gone || removed) && (
              <Banner tone="warning">
                <p>Задачу удалили, пока вы её редактировали.</p>
                {!readOnly && (
                  <Button variant="secondary" loading={saving} onClick={() => void recreate()}>
                    Создать заново
                  </Button>
                )}
              </Banner>
            )}
            <TextField
              label="Название"
              value={draft.title}
              maxLength={TITLE_MAX_LENGTH}
              error={errors.title}
              disabled={readOnly}
              onChange={(event) => set({ title: event.target.value })}
            />
            <div className={styles.row}>
              <SelectField
                label="Доска"
                value={draft.boardId}
                disabled={readOnly}
                options={
                  task && !writableBoards.some((item) => item.id === task.board_id)
                    ? [
                        { value: task.board_id, label: task.board_name },
                        ...writableBoards.map((item) => ({ value: item.id, label: item.name })),
                      ]
                    : writableBoards.map((item) => ({ value: item.id, label: item.name }))
                }
                hint={
                  task && draft.boardId !== task.board_id
                    ? "Метки сбросятся, а исполнители, которых нет на новой доске, будут сняты"
                    : undefined
                }
                onChange={(event) =>
                  set({
                    boardId: event.target.value,
                    columnId: event.target.value === base.boardId ? base.columnId : "",
                    labelIds: event.target.value === base.boardId ? base.labelIds : [],
                    assigneeIds: task ? draft.assigneeIds : [],
                  })
                }
              />
              <SelectField
                label="Колонка"
                value={draft.columnId}
                disabled={readOnly}
                options={[
                  ...(draft.columnId ? [] : [{ value: "", label: "Первая открытая" }]),
                  ...(columns ?? []).map((column) => ({ value: column.id, label: column.name })),
                ]}
                onChange={(event) => set({ columnId: event.target.value })}
              />
            </div>
            {noColumns && !columns && (
              <LoadError
                message="Не удалось загрузить колонки доски"
                onRetry={() => void reloadColumns()}
              />
            )}
            <TextArea
              label="Описание"
              value={draft.description}
              disabled={readOnly}
              onChange={(event) => set({ description: event.target.value })}
            />
            <SelectField
              label="Приоритет"
              value={draft.priority}
              options={PRIORITY_OPTIONS}
              disabled={readOnly}
              onChange={(event) => set({ priority: event.target.value })}
            />
            <div className={styles.row}>
              <TextField
                label="Дата начала"
                type="date"
                value={draft.startDate}
                error={errors.startDate}
                disabled={readOnly}
                onChange={(event) => set({ startDate: event.target.value })}
              />
              <TextField
                label="Дедлайн"
                type="date"
                value={draft.dueDate}
                error={errors.dueDate}
                disabled={readOnly}
                onChange={(event) => set({ dueDate: event.target.value })}
              />
              <TextField
                label="Время"
                type="time"
                value={draft.dueTime}
                disabled={readOnly}
                onChange={(event) => set({ dueTime: event.target.value })}
              />
            </div>
            <div className={styles.reminder}>
              <div className={styles.row}>
                <TextField
                  label="Напоминание"
                  type="date"
                  value={draft.reminderDate}
                  error={errors.reminder}
                  disabled={readOnly}
                  onChange={(event) => set({ reminderDate: event.target.value })}
                />
                <TextField
                  label="Время напоминания"
                  type="time"
                  value={draft.reminderTime}
                  disabled={readOnly}
                  onChange={(event) => set({ reminderTime: event.target.value })}
                />
              </div>
              <div className={styles.quick}>
                <Button
                  variant="ghost"
                  disabled={readOnly || !draft.dueDate}
                  onClick={() => set({ reminderDate: draft.dueDate, reminderTime: "09:00" })}
                >
                  В день срока в 09:00
                </Button>
                <Button
                  variant="ghost"
                  disabled={readOnly || !draft.dueDate}
                  onClick={() =>
                    set({ reminderDate: addDays(draft.dueDate, -1), reminderTime: "09:00" })
                  }
                >
                  За день в 09:00
                </Button>
                {(draft.reminderDate !== "" || draft.reminderTime !== "") && (
                  <Button
                    variant="ghost"
                    disabled={readOnly}
                    onClick={() => set({ reminderDate: "", reminderTime: "" })}
                  >
                    Без напоминания
                  </Button>
                )}
              </div>
            </div>
            {members && members.length > 0 && (
              <fieldset className={styles.assignees} disabled={readOnly}>
                <legend className={styles.legend}>Исполнители</legend>
                {members.map(({ user }) => (
                  <div key={user.id} className={styles.assignee}>
                    <Checkbox
                      label={user.display_name}
                      checked={draft.assigneeIds.includes(user.id)}
                      disabled={readOnly}
                      onChange={(checked) =>
                        set({
                          assigneeIds: checked
                            ? [...draft.assigneeIds, user.id]
                            : draft.assigneeIds.filter((id) => id !== user.id),
                        })
                      }
                    />
                    <Avatar name={user.display_name} color={user.color} size={26} />
                  </div>
                ))}
              </fieldset>
            )}
            <LabelPicker
              boardId={draft.boardId}
              value={draft.labelIds}
              disabled={readOnly}
              onChange={(labelIds) => set({ labelIds })}
            />
          </form>

          {task ? (
            <TaskChecklist task={task} readOnly={readOnly} />
          ) : (
            <DraftChecklist items={checklist} onChange={setChecklist} />
          )}
          {task && <TaskEventLinks task={task} readOnly={readOnly} />}
        </div>
        {task && board && (
          <TaskFeed task={task} board={board} readOnly={readOnly} timeZone={timeZone} />
        )}
      </div>

      {confirmingDelete && task && (
        <Dialog
          title="Удалить задачу?"
          width={420}
          onClose={() => setConfirmingDelete(false)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setConfirmingDelete(false)}>
                Отмена
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() =>
                  remove.mutate(task.id, {
                    onSuccess: onClose,
                    onError: (error) => {
                      setConfirmingDelete(false);
                      setFailure(failureMessage(error));
                    },
                  })
                }
              >
                Удалить
              </Button>
            </>
          }
        >
          <p>{task.title}</p>
        </Dialog>
      )}

      {conflict && (
        <ConflictDialog
          lastChange={conflict.lastChange}
          saving={saving}
          onClose={() => setConflict(null)}
          onShowNew={onReload}
          onOverwrite={() => {
            const expected = conflict.version;
            setConflict(null);
            void save(expected);
          }}
        />
      )}
    </Dialog>
  );
}

function NewTask({
  boardId,
  columnId,
  onClose,
}: {
  boardId?: string;
  columnId?: string;
  onClose: () => void;
}) {
  const { data: user } = useCurrentUser();
  const { data: boards, isPending, refetch } = useBoards();
  const personal = boards?.find((board) => board.is_default)?.id;
  const target = boardId ?? personal;

  if (isPending || !user || !target) {
    return (
      <Dialog title="Новая задача" width={640} onClose={onClose}>
        {isPending || !user ? (
          <Skeleton height={240} />
        ) : (
          <LoadError onRetry={() => void refetch()} />
        )}
      </Dialog>
    );
  }
  return (
    <TaskForm
      timeZone={user.timezone}
      onClose={onClose}
      onReload={onClose}
      initial={{
        title: "",
        boardId: target,
        columnId: columnId ?? "",
        description: "",
        priority: "3",
        startDate: "",
        dueDate: "",
        dueTime: "",
        reminderDate: "",
        reminderTime: "",
        assigneeIds: [],
        labelIds: [],
      }}
    />
  );
}

function ExistingTask({ id, onClose }: { id: string; onClose: () => void }) {
  const client = useQueryClient();
  const { data: user } = useCurrentUser();
  const { data: task, error, isPending, refetch } = useTask(id);
  // Bumped by "show the new version": the form rebuilds its draft from fresh data.
  const [revision, setRevision] = useState(0);

  if (task && user) {
    // A failed refetch keeps the last task next to the error, so the form stays and says it is gone.
    const removed = error instanceof ApiError && error.status === 404;
    return (
      <TaskForm
        key={revision}
        task={task}
        initial={draftOf(task, user.timezone)}
        timeZone={user.timezone}
        removed={removed}
        onClose={onClose}
        onReload={() => {
          void client.invalidateQueries({ queryKey: TASKS_KEY }).then(() => {
            setRevision((current) => current + 1);
          });
        }}
      />
    );
  }
  if (isPending || !user) {
    return (
      <Dialog title="Задача" width={640} onClose={onClose}>
        <Skeleton height={240} />
      </Dialog>
    );
  }
  return (
    <Dialog title="Задача" width={640} onClose={onClose}>
      {error instanceof ApiError && error.status === 404 ? (
        <EmptyState title="Объект больше не существует" />
      ) : (
        <LoadError message={failureMessage(error)} onRetry={() => void refetch()} />
      )}
    </Dialog>
  );
}

/** Mounted once in the shell, so a task opens over whatever screen is underneath. */
export function TaskDialogHost() {
  const { task, boardId, columnId, close } = useTaskParam();
  if (!task) return null;
  if (task === NEW_TASK) {
    return <NewTask boardId={boardId} columnId={columnId} onClose={close} />;
  }
  return <ExistingTask key={task} id={task} onClose={close} />;
}
