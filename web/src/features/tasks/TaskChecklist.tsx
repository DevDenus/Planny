import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import type { Task } from "../../api/client";
import { Checkbox, IconButton } from "../../ui";
import {
  useAddChecklistItem,
  useDeleteChecklistItem,
  useMoveChecklistItem,
  useToggleChecklistItem,
} from "./api";
import styles from "./TaskChecklist.module.css";

const ITEM_MAX_LENGTH = 500;

/** Not a form: the checklist sits next to the fields of the task form and forms can't nest. */
function ChecklistInput({ onAdd }: { onAdd: (text: string) => void }) {
  const [text, setText] = useState("");

  const add = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    setText("");
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    add();
  };

  return (
    <div className={styles.add}>
      <input
        className={styles.input}
        aria-label="Новый пункт"
        placeholder="Новый пункт"
        maxLength={ITEM_MAX_LENGTH}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <IconButton label="Добавить пункт" disabled={!text.trim()} onClick={add}>
        <Plus size={20} />
      </IconButton>
    </div>
  );
}

export type DraftChecklistProps = {
  items: string[];
  onChange: (items: string[]) => void;
};

/** A task that isn't saved yet has nothing to attach items to, they go with the first save. */
export function DraftChecklist({ items, onChange }: DraftChecklistProps) {
  return (
    <section className={styles.section}>
      <h3 className={styles.heading}>Чек-лист</h3>
      {items.length > 0 && (
        <ul className={styles.list}>
          {items.map((text, index) => (
            <li key={`${index}-${text}`} className={styles.item}>
              <span className={styles.text}>{text}</span>
              <IconButton
                label={`Удалить пункт: ${text}`}
                onClick={() => onChange(items.filter((_, other) => other !== index))}
              >
                <Trash2 size={18} />
              </IconButton>
            </li>
          ))}
        </ul>
      )}
      <ChecklistInput onAdd={(text) => onChange([...items, text])} />
    </section>
  );
}

export type TaskChecklistProps = {
  task: Task;
  readOnly: boolean;
};

export function TaskChecklist({ task, readOnly }: TaskChecklistProps) {
  const add = useAddChecklistItem(task.id);
  const toggle = useToggleChecklistItem(task.id);
  const move = useMoveChecklistItem(task.id);
  const remove = useDeleteChecklistItem(task.id);
  const items = task.checklist;

  return (
    <section className={styles.section}>
      <h3 className={styles.heading}>
        Чек-лист
        {items.length > 0 && (
          <span className={styles.progress}>
            {items.filter((item) => item.is_done).length}/{items.length}
          </span>
        )}
      </h3>
      {items.length > 0 && (
        <ul className={styles.list}>
          {items.map((item, index) => (
            <li key={item.id} className={styles.item}>
              <Checkbox
                className={styles.check}
                label={item.text}
                checked={item.is_done}
                disabled={readOnly}
                onChange={(done) => toggle.mutate({ itemId: item.id, done })}
              />
              {!readOnly && (
                <>
                  <IconButton
                    label={`Поднять: ${item.text}`}
                    disabled={index === 0}
                    onClick={() =>
                      move.mutate({
                        itemId: item.id,
                        afterId: items[index - 2]?.id ?? null,
                      })
                    }
                  >
                    <ArrowUp size={18} />
                  </IconButton>
                  <IconButton
                    label={`Опустить: ${item.text}`}
                    disabled={index === items.length - 1}
                    onClick={() =>
                      move.mutate({
                        itemId: item.id,
                        afterId: items[index + 1]?.id ?? null,
                      })
                    }
                  >
                    <ArrowDown size={18} />
                  </IconButton>
                  <IconButton
                    label={`Удалить пункт: ${item.text}`}
                    onClick={() => remove.mutate(item.id)}
                  >
                    <Trash2 size={18} />
                  </IconButton>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && <ChecklistInput onAdd={(text) => add.mutate(text)} />}
    </section>
  );
}
