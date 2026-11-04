import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { ApiError, type Label, type LabelColor } from "../../api/client";
import { Banner, Button, Dialog, IconButton, TextField } from "../../ui";
import { failureMessage } from "../tasks/api";
import { LabelChip } from "../tasks/LabelChip";
import { LabelColorPicker } from "../tasks/LabelPicker";
import { useCreateLabel, useDeleteLabel, useLabels, useUpdateLabel } from "./api";
import styles from "./BoardLabels.module.css";

const NAME_MAX_LENGTH = 50;

type EditorProps = {
  initial?: Label;
  boardId: string;
  onClose: () => void;
};

function LabelEditor({ initial, boardId, onClose }: EditorProps) {
  const create = useCreateLabel(boardId);
  const update = useUpdateLabel(boardId);
  const [name, setName] = useState(initial?.name ?? "");
  const [color, setColor] = useState<LabelColor>(initial?.color ?? "blue");
  const failed = create.error ?? update.error;
  const nameError = failed instanceof ApiError ? failed.fields.name : undefined;

  const save = () => {
    const body = { name: name.trim(), color };
    if (initial) update.mutate({ labelId: initial.id, ...body }, { onSuccess: onClose });
    else create.mutate(body, { onSuccess: onClose });
  };

  return (
    <div className={styles.editor}>
      {failed && !nameError && <Banner tone="error">{failureMessage(failed)}</Banner>}
      <TextField
        label="Название метки"
        value={name}
        maxLength={NAME_MAX_LENGTH}
        error={nameError}
        onChange={(event) => setName(event.target.value)}
      />
      <LabelColorPicker value={color} onChange={setColor} />
      <div className={styles.actions}>
        <Button variant="secondary" onClick={onClose}>
          Отмена
        </Button>
        <Button
          loading={create.isPending || update.isPending}
          disabled={!name.trim()}
          onClick={save}
        >
          Сохранить
        </Button>
      </div>
    </div>
  );
}

export function BoardLabels({ boardId, canEdit }: { boardId: string; canEdit: boolean }) {
  const { data: labels } = useLabels(boardId);
  const remove = useDeleteLabel(boardId);
  const [editing, setEditing] = useState<Label | "new" | null>(null);
  const [deleting, setDeleting] = useState<Label | null>(null);

  return (
    <section className={styles.section} aria-label="Метки доски">
      <h3 className={styles.title}>Метки</h3>
      {labels && labels.length === 0 && <p className={styles.empty}>Меток пока нет</p>}
      {labels && labels.length > 0 && (
        <ul className={styles.list}>
          {labels.map((label) => (
            <li key={label.id} className={styles.row}>
              <LabelChip label={label} />
              {canEdit && (
                <span className={styles.rowActions}>
                  <IconButton
                    label={`Изменить метку ${label.name}`}
                    onClick={() => setEditing(label)}
                  >
                    <Pencil size={16} />
                  </IconButton>
                  <IconButton
                    label={`Удалить метку ${label.name}`}
                    onClick={() => setDeleting(label)}
                  >
                    <Trash2 size={16} />
                  </IconButton>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit &&
        (editing ? (
          <LabelEditor
            key={editing === "new" ? "new" : editing.id}
            boardId={boardId}
            initial={editing === "new" ? undefined : editing}
            onClose={() => setEditing(null)}
          />
        ) : (
          <Button variant="secondary" onClick={() => setEditing("new")}>
            Добавить метку
          </Button>
        ))}
      {deleting && (
        <Dialog
          title={`Удалить метку «${deleting.name}»?`}
          width={420}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <Button variant="secondary" onClick={() => setDeleting(null)}>
                Отмена
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
              >
                Удалить
              </Button>
            </>
          }
        >
          {remove.error && <Banner tone="error">{failureMessage(remove.error)}</Banner>}
          <p>Метка исчезнет со всех карточек.</p>
        </Dialog>
      )}
    </section>
  );
}
