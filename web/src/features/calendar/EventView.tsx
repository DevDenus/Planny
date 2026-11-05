import {
  CheckSquare,
  Clock,
  LogOut,
  MapPin,
  Pencil,
  Square,
  Text,
  Trash2,
  Users,
} from "lucide-react";
import { useState } from "react";

import type { CalendarEvent } from "../../api/client";
import { Avatar, Banner, Button, Dialog, SelectField, useToast } from "../../ui";
import { failureMessage } from "../tasks/api";
import { useCategories, useDeleteEvent, useLeaveEvent, useUpdateEvent } from "./api";
import { useEventParam } from "./eventLinks";
import styles from "./EventView.module.css";
import { eventDays, eventTime } from "./items";
import { dayTitle } from "./period";

const NO_CATEGORY = "";

/** The day goes with the time, unless the time already names the days. */
function whenText(event: CalendarEvent, timeZone: string): string {
  const { first, last } = eventDays(event, timeZone);
  const time = eventTime(event, timeZone);
  return first === last ? `${dayTitle(first)} · ${time}` : time;
}

export type EventViewProps = { event: CalendarEvent; timeZone: string; onClose: () => void };

export function EventView({ event, timeZone, onClose }: EventViewProps) {
  const toast = useToast();
  const { edit, switchToTask } = useEventParam();
  const { data: categories } = useCategories();
  const update = useUpdateEvent(event.id);
  const remove = useDeleteEvent();
  const leave = useLeaveEvent();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [failure, setFailure] = useState<string>();
  const shared = event.participants.length > 1;

  const footer = (
    <div className={styles.actions}>
      <Button icon={<Pencil size={18} />} onClick={edit}>
        Изменить
      </Button>
      <Button
        variant="danger"
        icon={<Trash2 size={18} />}
        onClick={() => setConfirmingDelete(true)}
      >
        Удалить
      </Button>
      {shared && (
        <Button
          variant="ghost"
          className={styles.leave}
          icon={<LogOut size={18} />}
          loading={leave.isPending}
          onClick={() =>
            leave.mutate(event.id, {
              onSuccess: onClose,
              onError: (error) => setFailure(failureMessage(error)),
            })
          }
        >
          Выйти из события
        </Button>
      )}
    </div>
  );

  return (
    <Dialog title={event.title} width={640} onClose={onClose} footer={footer}>
      <div className={styles.view}>
        {failure && <Banner tone="error">{failure}</Banner>}
        <p className={styles.row}>
          <Clock size={18} aria-hidden="true" />
          {whenText(event, timeZone)}
        </p>
        {event.location && (
          <p className={styles.row}>
            <MapPin size={18} aria-hidden="true" />
            {event.location}
          </p>
        )}
        {event.description && (
          <p className={styles.row}>
            <Text size={18} aria-hidden="true" />
            <span className={styles.description}>{event.description}</span>
          </p>
        )}
        <div className={styles.row}>
          <Users size={18} aria-hidden="true" />
          <ul className={styles.people} aria-label="Участники">
            {event.participants.map((person) => (
              <li key={person.id} className={styles.person}>
                <Avatar name={person.display_name} color={person.color} size={26} />
                {person.display_name}
              </li>
            ))}
          </ul>
        </div>
        <SelectField
          label="Категория"
          value={event.category_id ?? NO_CATEGORY}
          options={[
            { value: NO_CATEGORY, label: "Без категории" },
            ...(categories ?? []).map((category) => ({
              value: category.id,
              label: category.name,
            })),
          ]}
          onChange={(change) =>
            update.mutate(
              { version: event.version, category_id: change.target.value || null },
              { onError: (error) => toast.show(failureMessage(error), "error") },
            )
          }
        />
        {event.linked_tasks.length > 0 && (
          <section className={styles.tasks}>
            <h3 className={styles.heading}>Связанные задачи</h3>
            <ul className={styles.taskList}>
              {event.linked_tasks.map((task) => {
                const Icon = task.completed_at === null ? Square : CheckSquare;
                return (
                  <li key={task.id}>
                    <button
                      type="button"
                      className={styles.task}
                      onClick={() => switchToTask(task.id)}
                    >
                      <Icon size={18} aria-hidden="true" />
                      {task.title}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>

      {confirmingDelete && (
        <Dialog
          title="Удалить событие?"
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
                  remove.mutate(event.id, {
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
          <p>{shared ? "Событие удалится у всех участников" : event.title}</p>
        </Dialog>
      )}
    </Dialog>
  );
}
