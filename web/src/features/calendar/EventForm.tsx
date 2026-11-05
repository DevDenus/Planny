import { useMemo, useState, type FormEvent } from "react";

import {
  ApiError,
  type CalendarEvent,
  type EventCreate,
  type EventUpdate,
  type UserSummary,
} from "../../api/client";
import {
  Avatar,
  Banner,
  Button,
  Checkbox,
  ConflictDialog,
  Dialog,
  SelectField,
  Switch,
  TextArea,
  TextField,
  useToast,
} from "../../ui";
import { useCurrentUser } from "../auth/session";
import { useUsers } from "../boards/api";
import { failureMessage } from "../tasks/api";
import { fromLocalInput, toLocalInput } from "../tasks/dates";
import { useCategories, useCreateEvent, useLinkEvent, useUpdateEvent } from "./api";
import { BusyHint } from "./BusyHint";
import styles from "./EventForm.module.css";

const TITLE_MAX_LENGTH = 200;
const LOCATION_MAX_LENGTH = 500;
const NO_CATEGORY = "";
/** What the time fields hold after "all day" is switched off on an event that had no time. */
const DEFAULT_START = "09:00";
const DEFAULT_END = "10:00";
/** The event was deleted while the form was open. */
const GONE = "Событие удалили, пока вы его редактировали";

export type EventDraft = {
  title: string;
  allDay: boolean;
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
  participantIds: string[];
  categoryId: string;
  location: string;
  description: string;
};

type FieldErrors = { title?: string; start?: string; end?: string };

export function draftOf(event: CalendarEvent, timeZone: string): EventDraft {
  const start = toLocalInput(event.start_at, timeZone);
  const end = toLocalInput(event.end_at, timeZone);
  return {
    title: event.title,
    allDay: event.all_day,
    startDate: event.start_date ?? start.date,
    startTime: start.time,
    endDate: event.end_date ?? end.date,
    endTime: end.time,
    participantIds: event.participants.map((person) => person.id),
    categoryId: event.category_id ?? NO_CATEGORY,
    location: event.location ?? "",
    description: event.description ?? "",
  };
}

export function newDraft(
  userId: string,
  day: string,
  time: string | undefined,
  title = "",
): EventDraft {
  const hour = Number((time ?? DEFAULT_START).slice(0, 2));
  const pad = (value: number) => String(value).padStart(2, "0");
  const startTime = time ?? DEFAULT_START;
  // At the last hour the event ends at the end of the day rather than on the next one.
  const endTime = hour >= 23 ? "23:59" : `${pad(hour + 1)}:${startTime.slice(3)}`;
  return {
    title,
    allDay: false,
    startDate: day,
    startTime,
    endDate: day,
    endTime,
    participantIds: [userId],
    categoryId: NO_CATEGORY,
    location: "",
    description: "",
  };
}

function eventTime(draft: EventDraft, timeZone: string) {
  if (draft.allDay) {
    return {
      all_day: true,
      start_date: draft.startDate,
      end_date: draft.endDate,
      start_at: null,
      end_at: null,
    };
  }
  return {
    all_day: false,
    start_date: null,
    end_date: null,
    start_at: fromLocalInput(draft.startDate, draft.startTime, timeZone),
    end_at: fromLocalInput(draft.endDate, draft.endTime, timeZone),
  };
}

function sameIds(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((id) => right.includes(id));
}

/** Same days and, for a timed event, same clock times. */
function sameTime(left: EventDraft, right: EventDraft): boolean {
  return (
    left.allDay === right.allDay &&
    left.startDate === right.startDate &&
    left.endDate === right.endDate &&
    (left.allDay || (left.startTime === right.startTime && left.endTime === right.endTime))
  );
}

function changes(
  before: EventDraft,
  draft: EventDraft,
  timeZone: string,
): Omit<EventUpdate, "version"> {
  const timeChanged = !sameTime(before, draft);
  return {
    ...(draft.title.trim() !== before.title && { title: draft.title.trim() }),
    ...(draft.description.trim() !== before.description && {
      description: draft.description.trim() || null,
    }),
    ...(draft.location.trim() !== before.location && { location: draft.location.trim() || null }),
    ...(timeChanged && eventTime(draft, timeZone)),
    ...(!sameIds(draft.participantIds, before.participantIds) && {
      participant_ids: draft.participantIds,
    }),
    ...(draft.categoryId !== before.categoryId && { category_id: draft.categoryId || null }),
  };
}

function createBody(draft: EventDraft, timeZone: string, id: string): EventCreate {
  return {
    id,
    title: draft.title.trim(),
    description: draft.description.trim() || null,
    location: draft.location.trim() || null,
    ...eventTime(draft, timeZone),
    timezone: timeZone,
    participant_ids: draft.participantIds,
    category_id: draft.categoryId || null,
  };
}

/**
 * Dates sort as text, and so do times on one day. A time the form didn't change was accepted by
 * the server, and across a clock change an end can read earlier than its start, so with `saved`,
 * the draft the event was read with, the order is not checked again for an unchanged time.
 */
export function validate(draft: EventDraft, saved?: EventDraft): FieldErrors {
  const errors: FieldErrors = {};
  if (!draft.title.trim()) errors.title = "Введите название";
  if (!draft.startDate || (!draft.allDay && !draft.startTime)) errors.start = "Укажите начало";
  if (!draft.endDate || (!draft.allDay && !draft.endTime)) errors.end = "Укажите конец";
  if (errors.start || errors.end) return errors;
  if (saved !== undefined && sameTime(draft, saved)) return errors;
  if (draft.endDate < draft.startDate) {
    errors.end = "Конец не может быть раньше начала";
  } else if (
    !draft.allDay &&
    draft.endDate === draft.startDate &&
    draft.endTime <= draft.startTime
  ) {
    errors.end = "Конец должен быть позже начала";
  }
  return errors;
}

/** A start moved past the end takes the end along, so the form is never left broken by one move. */
function withStart(draft: EventDraft, startDate: string, startTime: string): EventDraft {
  const next = { ...draft, startDate, startTime };
  if (startDate > draft.endDate) next.endDate = startDate;
  if (!draft.allDay && next.endDate === startDate && draft.endTime <= startTime) {
    const hour = Number(startTime.slice(0, 2));
    next.endTime =
      hour >= 23 ? "23:59" : `${String(hour + 1).padStart(2, "0")}${startTime.slice(2)}`;
  }
  return next;
}

export type EventFormProps = {
  /** Without an event the form creates one. */
  event?: CalendarEvent;
  initial: EventDraft;
  /** The task the new event is planned for: they get linked. */
  taskId?: string;
  timeZone: string;
  /** The event was deleted in the background: the typed text stays, and the form says so. */
  gone?: boolean;
  onClose: () => void;
};

export function EventForm({ event, initial, taskId, timeZone, gone, onClose }: EventFormProps) {
  const { data: user } = useCurrentUser();
  const { data: users } = useUsers(true);
  const { data: categories } = useCategories();
  const create = useCreateEvent();
  const update = useUpdateEvent(event?.id ?? "");
  const link = useLinkEvent(taskId ?? "");
  const toast = useToast();
  const [newId] = useState(() => crypto.randomUUID());
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState(initial);
  const [version, setVersion] = useState(event?.version ?? 0);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [failure, setFailure] = useState<string>();
  const [conflict, setConflict] = useState<CalendarEvent | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (change: Partial<EventDraft>) => {
    setDraft((current) => ({ ...current, ...change }));
    setErrors({});
  };

  // People who are in the event stay listed even when they aren't active any more.
  const people = useMemo(() => {
    const everyone = new Map<string, UserSummary>();
    for (const person of [...(event?.participants ?? []), ...(users ?? [])]) {
      everyone.set(person.id, person);
    }
    if (user) everyone.set(user.id, user);
    return [...everyone.values()];
  }, [event, users, user]);
  const chosen = people.filter((person) => draft.participantIds.includes(person.id));

  const moments =
    !draft.allDay && Object.keys(validate(draft)).every((field) => field === "title")
      ? eventTime(draft, timeZone)
      : null;

  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.code === "version_conflict") {
      setConflict((error.details as { current: CalendarEvent }).current);
    } else if (error instanceof ApiError && error.status === 404) {
      setFailure(GONE);
    } else if (error instanceof ApiError && Object.keys(error.fields).length > 0) {
      const { title, start_at, start_date, end_at, end_date } = error.fields;
      const known = { title, start: start_at ?? start_date, end: end_at ?? end_date };
      setErrors(known);
      if (!known.title && !known.start && !known.end) setFailure(failureMessage(error));
    } else {
      setFailure(failureMessage(error));
    }
  };

  const save = async (expected: number) => {
    setFailure(undefined);
    setSaving(true);
    try {
      if (event) {
        const body = changes(base, draft, timeZone);
        if (Object.keys(body).length > 0) {
          await update.mutateAsync({ ...body, version: expected });
        }
      } else {
        const created = await create.mutateAsync(createBody(draft, timeZone, newId));
        if (taskId) {
          // The event exists now: a retry would post it again, so the form closes all the same.
          try {
            await link.mutateAsync(created.id);
          } catch {
            toast.show("Событие создано, но связать с задачей не удалось", "error");
          }
        }
      }
      onClose();
    } catch (error) {
      fail(error);
    } finally {
      setSaving(false);
    }
  };

  const submit = (formEvent: FormEvent) => {
    formEvent.preventDefault();
    const found = validate(draft, event ? base : undefined);
    setErrors(found);
    if (Object.keys(found).length === 0) void save(version);
  };

  const footer = (
    <>
      <Button variant="secondary" onClick={onClose}>
        Отмена
      </Button>
      <Button type="submit" form="event-form" loading={saving}>
        {event ? "Сохранить" : "Создать"}
      </Button>
    </>
  );

  return (
    <Dialog
      title={event ? "Изменить событие" : "Новое событие"}
      width={640}
      onClose={onClose}
      footer={footer}
    >
      <form id="event-form" className={styles.form} onSubmit={submit} noValidate>
        {gone && failure !== GONE && <Banner tone="error">{GONE}</Banner>}
        {failure && <Banner tone="error">{failure}</Banner>}
        <TextField
          label="Название"
          value={draft.title}
          maxLength={TITLE_MAX_LENGTH}
          error={errors.title}
          onChange={(change) => set({ title: change.target.value })}
        />
        <Switch
          className={styles.allDay}
          label="Весь день"
          checked={draft.allDay}
          onChange={(allDay) =>
            set({
              allDay,
              startTime: draft.startTime || DEFAULT_START,
              endTime: draft.endTime || DEFAULT_END,
            })
          }
        />
        <div className={styles.moment}>
          <TextField
            label="Начало"
            type="date"
            value={draft.startDate}
            error={errors.start}
            onChange={(change) => set(withStart(draft, change.target.value, draft.startTime))}
          />
          {!draft.allDay && (
            <TextField
              label="Время начала"
              type="time"
              value={draft.startTime}
              onChange={(change) => set(withStart(draft, draft.startDate, change.target.value))}
            />
          )}
        </div>
        <div className={styles.moment}>
          <TextField
            label="Конец"
            type="date"
            value={draft.endDate}
            error={errors.end}
            onChange={(change) => set({ endDate: change.target.value })}
          />
          {!draft.allDay && (
            <TextField
              label="Время конца"
              type="time"
              value={draft.endTime}
              onChange={(change) => set({ endTime: change.target.value })}
            />
          )}
        </div>
        <fieldset className={styles.people}>
          <legend className={styles.legend}>Участники</legend>
          {people.map((person) => (
            <div key={person.id} className={styles.person}>
              <Checkbox
                label={person.display_name}
                checked={draft.participantIds.includes(person.id)}
                // Leaving is a separate action, with its own consequences for the event.
                disabled={person.id === user?.id}
                onChange={(checked) =>
                  set({
                    participantIds: checked
                      ? [...draft.participantIds, person.id]
                      : draft.participantIds.filter((id) => id !== person.id),
                  })
                }
              />
              <Avatar name={person.display_name} color={person.color} size={26} />
            </div>
          ))}
        </fieldset>
        <BusyHint
          people={chosen}
          day={draft.startDate}
          start={moments?.start_at ?? null}
          end={moments?.end_at ?? null}
          timeZone={timeZone}
          excludeEventId={event?.id}
        />
        <SelectField
          label="Категория"
          value={draft.categoryId}
          options={[
            { value: NO_CATEGORY, label: "Без категории" },
            ...(categories ?? []).map((category) => ({
              value: category.id,
              label: category.name,
            })),
          ]}
          onChange={(change) => set({ categoryId: change.target.value })}
        />
        <TextField
          label="Место"
          value={draft.location}
          maxLength={LOCATION_MAX_LENGTH}
          onChange={(change) => set({ location: change.target.value })}
        />
        <TextArea
          label="Описание"
          value={draft.description}
          onChange={(change) => set({ description: change.target.value })}
        />
      </form>

      {conflict && (
        <ConflictDialog
          saving={saving}
          onClose={() => setConflict(null)}
          onShowNew={() => {
            const fresh = draftOf(conflict, timeZone);
            setBase(fresh);
            setDraft(fresh);
            setVersion(conflict.version);
            setConflict(null);
          }}
          onOverwrite={() => {
            const expected = conflict.version;
            setVersion(expected);
            setConflict(null);
            void save(expected);
          }}
        />
      )}
    </Dialog>
  );
}
