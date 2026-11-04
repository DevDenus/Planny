import { Plus } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { IconButton } from "../../ui";
import { useQuickAdd, type QuickAddTarget } from "./api";
import styles from "./QuickAdd.module.css";

const TITLE_MAX_LENGTH = 200;

export type QuickAddProps = {
  target: QuickAddTarget | undefined;
  placeholder?: string;
};

export function QuickAdd({ target, placeholder = "Быстро добавить задачу" }: QuickAddProps) {
  const { mutateAsync } = useQuickAdd();
  const [title, setTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  // The last add that failed. Sending the same text again reuses its id.
  const failed = useRef<{ id: string; title: string } | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed || !target) return;
    // The id comes from here, so a repeated request can't create a second card.
    const id = failed.current?.title === trimmed ? failed.current.id : crypto.randomUUID();
    failed.current = null;
    // mutate reports only the latest call, and several items can be added in quick succession.
    mutateAsync({ id, title: trimmed, target }).catch(() => {
      // The toast and the rollback are in the hook. Only the text is given back here, and
      // only while the field is still empty, so text the user is typing now is left alone.
      if (inputRef.current?.value === "") {
        failed.current = { id, title: trimmed };
        setTitle(trimmed);
      }
    });
    setTitle("");
  };

  return (
    <form className={styles.form} onSubmit={submit}>
      <input
        ref={inputRef}
        className={styles.input}
        aria-label={placeholder}
        placeholder={placeholder}
        maxLength={TITLE_MAX_LENGTH}
        value={title}
        disabled={!target}
        onChange={(event) => setTitle(event.target.value)}
      />
      <IconButton
        type="submit"
        label="Добавить"
        disabled={!target || !title.trim()}
        className={styles.submit}
      >
        <Plus size={20} />
      </IconButton>
    </form>
  );
}
