import { useState, type FormEvent } from "react";

import { ApiError, type BoardColumn } from "../../../api/client";
import { Banner, Button, Dialog, SelectField, TextField, useFocusInvalid } from "../../../ui";
import { failureMessage } from "../../tasks/api";
import { pluralize } from "../../tasks/labels";
import { useCreateColumn, useDeleteColumn, useUpdateColumn } from "../api";

const NAME_MAX_LENGTH = 100;

function cards(count: number): string {
  return `${count} ${pluralize(count, "карточка", "карточки", "карточек")}`;
}

type NameDialogProps = {
  title: string;
  initial: string;
  saving: boolean;
  failure?: string;
  onSubmit: (name: string) => void;
  onClose: () => void;
};

function NameDialog({ title, initial, saving, failure, onSubmit, onClose }: NameDialogProps) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState<string>();
  const form = useFocusInvalid(error);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) onSubmit(name.trim());
    else setError("Введите название");
  };

  return (
    <Dialog
      title={title}
      width={420}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" form="column-name-form" loading={saving}>
            Сохранить
          </Button>
        </>
      }
    >
      <form id="column-name-form" ref={form} onSubmit={submit} noValidate>
        {failure && <Banner tone="error">{failure}</Banner>}
        <TextField
          label="Название"
          value={name}
          maxLength={NAME_MAX_LENGTH}
          error={error}
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
      </form>
    </Dialog>
  );
}

export function NewColumnDialog({ boardId, onClose }: { boardId: string; onClose: () => void }) {
  const create = useCreateColumn(boardId);
  // One id for the life of the dialog, so a retry after a lost response adds no second column.
  const [id] = useState(() => crypto.randomUUID());
  return (
    <NameDialog
      title="Новая колонка"
      initial=""
      saving={create.isPending}
      failure={create.error ? failureMessage(create.error) : undefined}
      onSubmit={(name) => create.mutate({ id, name, is_done: false }, { onSuccess: onClose })}
      onClose={onClose}
    />
  );
}

type ColumnDialogProps = {
  boardId: string;
  column: BoardColumn;
  onClose: () => void;
};

export function RenameColumnDialog({ boardId, column, onClose }: ColumnDialogProps) {
  const update = useUpdateColumn(boardId);
  return (
    <NameDialog
      title="Переименовать колонку"
      initial={column.name}
      saving={update.isPending}
      failure={update.error ? failureMessage(update.error) : undefined}
      onSubmit={(name) =>
        update.mutate({ columnId: column.id, body: { name } }, { onSuccess: onClose })
      }
      onClose={onClose}
    />
  );
}

export function DoneColumnDialog({ boardId, column, onClose }: ColumnDialogProps) {
  const update = useUpdateColumn(boardId);
  const count = column.task_count;
  const warning = column.is_done
    ? `Отметка о выполнении будет снята у ${count} ${pluralize(count, "карточки", "карточек", "карточек")}`
    : `${count === 1 ? "Будет отмечена выполненной" : "Будут отмечены выполненными"} ${cards(count)}`;

  return (
    <Dialog
      title={column.is_done ? "Снять отметку завершающей?" : "Сделать колонку завершающей?"}
      width={420}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            loading={update.isPending}
            onClick={() =>
              update.mutate(
                { columnId: column.id, body: { is_done: !column.is_done } },
                { onSuccess: onClose },
              )
            }
          >
            Подтвердить
          </Button>
        </>
      }
    >
      {update.error && <Banner tone="error">{failureMessage(update.error)}</Banner>}
      <p>{warning}</p>
    </Dialog>
  );
}

type DeleteColumnDialogProps = ColumnDialogProps & { columns: BoardColumn[] };

export function DeleteColumnDialog({ boardId, column, columns, onClose }: DeleteColumnDialogProps) {
  const remove = useDeleteColumn(boardId);
  const others = columns.filter((item) => item.id !== column.id);
  const [moveTo, setMoveTo] = useState(others[0]?.id ?? "");
  const fieldError = remove.error instanceof ApiError ? remove.error.fields.move_to : undefined;

  return (
    <Dialog
      title={`Удалить колонку «${column.name}»?`}
      width={420}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="danger"
            loading={remove.isPending}
            // Sent for an empty column too: it may still hold deleted cards the user can't see.
            onClick={() => remove.mutate({ columnId: column.id, moveTo }, { onSuccess: onClose })}
          >
            Удалить
          </Button>
        </>
      }
    >
      {remove.error && !fieldError && <Banner tone="error">{failureMessage(remove.error)}</Banner>}
      {column.task_count > 0 ? (
        <SelectField
          label={`Куда перенести ${cards(column.task_count)}`}
          value={moveTo}
          error={fieldError}
          options={others.map((item) => ({ value: item.id, label: item.name }))}
          onChange={(event) => setMoveTo(event.target.value)}
        />
      ) : (
        <p>В колонке нет карточек.</p>
      )}
    </Dialog>
  );
}
