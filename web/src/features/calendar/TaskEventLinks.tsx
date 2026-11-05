import { CalendarPlus, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { EventSummary, Task } from "../../api/client";
import { Button, IconButton, TextField, useToast } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { failureMessage } from "../tasks/api";
import { deadlineDay } from "../tasks/dates";
import { useLinkEvent, useSearch, useUnlinkEvent } from "./api";
import { useEventParam } from "./eventLinks";
import { eventWhen } from "./items";
import styles from "./TaskEventLinks.module.css";

const SEARCH_DELAY_MS = 250;

function EventPicker({
  linked,
  timeZone,
  onPick,
}: {
  linked: EventSummary[];
  timeZone: string;
  onPick: (id: string) => void;
}) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const { data } = useSearch(query);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(text.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);

  const found = query ? data?.events.filter(({ id }) => !linked.some((e) => e.id === id)) : [];
  return (
    <div className={styles.picker}>
      <TextField
        hideLabel
        label="Найти событие"
        value={text}
        onChange={(change) => setText(change.target.value)}
      />
      {found && found.length > 0 && (
        <ul className={styles.list} aria-label="Найденные события">
          {found.map((event) => (
            <li key={event.id}>
              <button
                type="button"
                className={styles.found}
                onClick={() => {
                  onPick(event.id);
                  setText("");
                }}
              >
                <span className={styles.title}>{event.title}</span>
                <span className={styles.when}>{eventWhen(event, timeZone)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type TaskEventLinksProps = { task: Task; readOnly: boolean };

/** Time for a task is planned as an event: it doesn't take any time by itself. */
export function TaskEventLinks({ task, readOnly }: TaskEventLinksProps) {
  const { data: user } = useCurrentUser();
  const timeZone = user?.timezone ?? "UTC";
  const toast = useToast();
  const { open, create } = useEventParam();
  const link = useLinkEvent(task.id);
  const unlink = useUnlinkEvent(task.id);
  const failed = (error: unknown) => toast.show(failureMessage(error), "error");
  const day = deadlineDay(task, timeZone) ?? undefined;

  return (
    <section className={styles.links}>
      <h3 className={styles.heading}>Связанные события</h3>
      {task.linked_events.length > 0 && (
        <ul className={styles.list}>
          {task.linked_events.map((event) => (
            <li key={event.id} className={styles.row}>
              <button
                type="button"
                className={styles.found}
                onClick={() => open(event.id, event.next_occurrence_start ?? undefined)}
              >
                <span className={styles.title}>{event.title}</span>
                <span className={styles.when}>{eventWhen(event, timeZone)}</span>
              </button>
              {!readOnly && (
                <IconButton
                  label={`Убрать связь: ${event.title}`}
                  onClick={() => unlink.mutate(event.id, { onError: failed })}
                >
                  <X size={18} />
                </IconButton>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <>
          <EventPicker
            linked={task.linked_events}
            timeZone={timeZone}
            onPick={(id) => link.mutate(id, { onError: failed })}
          />
          <Button
            variant="secondary"
            icon={<CalendarPlus size={18} />}
            onClick={() => create({ day, taskId: task.id })}
          >
            Создать событие
          </Button>
        </>
      )}
    </section>
  );
}
