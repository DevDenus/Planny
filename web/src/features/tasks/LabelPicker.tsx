import { useState, type KeyboardEvent } from "react";

import { ApiError, type LabelColor } from "../../api/client";
import { Button, Checkbox, TextField, cx } from "../../ui";
import { useCreateLabel, useLabels } from "../boards/api";
import { failureMessage } from "./api";
import { LabelChip } from "./LabelChip";
import styles from "./LabelPicker.module.css";
import { LABEL_COLORS } from "./labels";

const NAME_MAX_LENGTH = 50;

export type LabelColorPickerProps = {
  value: LabelColor;
  onChange: (color: LabelColor) => void;
};

export function LabelColorPicker({ value, onChange }: LabelColorPickerProps) {
  return (
    <div className={styles.colors} role="radiogroup" aria-label="Цвет метки">
      {LABEL_COLORS.map((color) => (
        <button
          key={color.value}
          type="button"
          role="radio"
          aria-checked={value === color.value}
          aria-label={color.label}
          title={color.label}
          className={cx(styles.color, value === color.value && styles.colorChosen)}
          style={{ background: `var(--cat-${color.value})` }}
          onClick={() => onChange(color.value)}
        />
      ))}
    </div>
  );
}

export type LabelPickerProps = {
  boardId: string;
  value: string[];
  disabled?: boolean;
  onChange: (labelIds: string[]) => void;
};

export function LabelPicker({ boardId, value, disabled, onChange }: LabelPickerProps) {
  const { data: labels } = useLabels(boardId);
  const create = useCreateLabel(boardId);
  const [name, setName] = useState("");
  const [color, setColor] = useState<LabelColor>("blue");
  const [adding, setAdding] = useState(false);

  const add = () => {
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), color },
      {
        onSuccess: (label) => {
          onChange([...value, label.id]);
          setName("");
          setAdding(false);
        },
      },
    );
  };

  // The picker sits inside the task form, and Enter here must not save the task.
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault();
      add();
    }
  };

  if (!labels) return null;
  const failure =
    create.error instanceof ApiError
      ? (create.error.fields.name ?? failureMessage(create.error))
      : undefined;

  return (
    <fieldset className={styles.picker} disabled={disabled}>
      <legend className={styles.legend}>Метки</legend>
      {labels.length > 0 && (
        <div className={styles.options}>
          {labels.map((label) => (
            <div key={label.id} className={styles.option}>
              <Checkbox
                hideLabel
                label={label.name}
                checked={value.includes(label.id)}
                disabled={disabled}
                onChange={(checked) =>
                  onChange(checked ? [...value, label.id] : value.filter((id) => id !== label.id))
                }
              />
              <LabelChip label={label} />
            </div>
          ))}
        </div>
      )}
      {!disabled &&
        (adding ? (
          <div className={styles.add}>
            <TextField
              hideLabel
              label="Название метки"
              value={name}
              maxLength={NAME_MAX_LENGTH}
              error={failure}
              autoFocus
              onKeyDown={onKeyDown}
              onChange={(event) => setName(event.target.value)}
            />
            <LabelColorPicker value={color} onChange={setColor} />
            <div className={styles.addActions}>
              <Button variant="secondary" onClick={() => setAdding(false)}>
                Отмена
              </Button>
              <Button loading={create.isPending} disabled={!name.trim()} onClick={add}>
                Добавить метку
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="ghost" onClick={() => setAdding(true)}>
            Новая метка
          </Button>
        ))}
    </fieldset>
  );
}
