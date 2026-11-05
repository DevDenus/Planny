import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { SearchResults } from "../../api/client";
import { Banner, Dialog, IconButton, Spinner, TextField, cx } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { useSearch } from "../calendar/api";
import { useEventParam } from "../calendar/eventLinks";
import { eventWhen } from "../calendar/items";
import { useTaskParam } from "../tasks/taskLinks";
import styles from "./SearchBox.module.css";

const DEBOUNCE_MS = 250;

/** The value as it is `delay` ms after its last change. */
function useDebounced(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

type ResultsProps = {
  results: SearchResults | undefined;
  failed: boolean;
  timeZone: string;
  onEvent: (id: string, occurrence?: string) => void;
  onTask: (id: string) => void;
};

function Results({ results, failed, timeZone, onEvent, onTask }: ResultsProps) {
  if (failed) return <Banner tone="error">Не удалось выполнить поиск</Banner>;
  if (!results) {
    return (
      <div className={styles.status}>
        <Spinner />
      </div>
    );
  }
  const { events, tasks } = results;
  if (events.length === 0 && tasks.length === 0) {
    return <p className={styles.status}>Ничего не найдено</p>;
  }
  return (
    <>
      {events.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.heading}>События</h3>
          <ul className={styles.list}>
            {events.map((event) => {
              const when = eventWhen(event, timeZone);
              return (
                <li key={event.id}>
                  <button
                    type="button"
                    className={styles.item}
                    onClick={() => onEvent(event.id, event.next_occurrence_start ?? undefined)}
                  >
                    <span className={styles.title}>{event.title}</span>
                    {when && <span className={styles.meta}>{when}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {tasks.length > 0 && (
        <section className={styles.section}>
          <h3 className={styles.heading}>Задачи</h3>
          <ul className={styles.list}>
            {tasks.map((task) => (
              <li key={task.id}>
                <button type="button" className={styles.item} onClick={() => onTask(task.id)}>
                  <span className={cx(styles.title, task.completed_at !== null && styles.done)}>
                    {task.title}
                  </span>
                  <span className={styles.meta}>{task.board_name}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

type FieldProps = {
  /** The top bar: the results float under the input, and Escape or a click outside closes them. */
  dropdown?: boolean;
  /** Runs after a result is chosen, so the owner can close what holds the field. */
  onChosen?: () => void;
};

/** The input and its results. The top bar shows the results as a dropdown, the phone dialog inline. */
function SearchField({ dropdown = false, onChosen }: FieldProps) {
  const [text, setText] = useState("");
  const [expanded, setExpanded] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const { open: openEvent } = useEventParam();
  const { open: openTask } = useTaskParam();
  const timeZone = useCurrentUser().data?.timezone ?? "UTC";

  const query = text.trim();
  const shown = query !== "" && (!dropdown || expanded);
  const debounced = useDebounced(query, DEBOUNCE_MS);
  // Blank text, or a closed dropdown, sends no request.
  const { data, isError } = useSearch(shown ? debounced : "");

  useEffect(() => {
    if (!dropdown || !expanded) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setExpanded(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [dropdown, expanded]);

  // The text is cleared, so the next search starts empty.
  const choose = (go: () => void) => {
    setText("");
    setExpanded(false);
    go();
    onChosen?.();
  };

  return (
    <div ref={root} className={styles.box}>
      <TextField
        type="search"
        label="Поиск"
        aria-label="Поиск"
        hideLabel
        placeholder="Поиск по событиям и задачам"
        icon={<Search size={20} aria-hidden="true" />}
        value={text}
        onFocus={() => setExpanded(true)}
        onChange={(event) => {
          setText(event.target.value);
          setExpanded(true);
        }}
        onKeyDown={(event) => {
          if (dropdown && event.key === "Escape") setExpanded(false);
        }}
      />
      {shown && (
        <div className={dropdown ? styles.dropdown : undefined}>
          <Results
            results={data}
            failed={isError}
            timeZone={timeZone}
            onEvent={(id, occurrence) => choose(() => openEvent(id, occurrence))}
            onTask={(id) => choose(() => openTask(id))}
          />
        </div>
      )}
    </div>
  );
}

/** The top bar of the desktop: the input, with the results in a dropdown under it. */
export function SearchBox() {
  return <SearchField dropdown />;
}

/** The phone header: an icon that opens the same search in a dialog. */
export function SearchButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <IconButton label="Поиск" onClick={() => setOpen(true)}>
        <Search size={20} />
      </IconButton>
      {open && (
        <Dialog title="Поиск" onClose={() => setOpen(false)}>
          <SearchField onChosen={() => setOpen(false)} />
        </Dialog>
      )}
    </>
  );
}
