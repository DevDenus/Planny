import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState, type RefObject } from "react";
import { useNavigate } from "react-router";

import { ApiError, type AssistantCard, type EventCard, type TaskCard } from "../../api/client";
import { ASSISTANT_KEY, TASKS_KEY } from "../../api/queryClient";
import { EmptyState, LoadError, Skeleton, useToast } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { useBoards } from "../boards/api";
import { useEvent } from "../calendar/api";
import { EventForm, draftOf as eventDraftOf, type EventDraft } from "../calendar/EventForm";
import { failureMessage, useTask } from "../tasks/api";
import { TaskForm, draftOf as taskDraftOf, type Draft } from "../tasks/TaskDialog";
import {
  cardFromEventDraft,
  cardFromTaskDraft,
  eventDraftFromCard,
  eventProposedOnBase,
  taskDraftFromCard,
  taskProposedOnBase,
} from "./cards";
import styles from "./CardPanel.module.css";

export type CardPanelProps = {
  chatId: string;
  created: boolean;
  /** Where the form leaves what the user has typed in it, for the next message. */
  draftRef: RefObject<AssistantCard | null>;
};

/** What happens when the card became a task or an event: a note, and a look at the result. */
function useAfterSave() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  return (message: string, target: string) => {
    void client.invalidateQueries({ queryKey: ASSISTANT_KEY });
    toast.show(message);
    void navigate(target);
  };
}

function Loading() {
  return <Skeleton height={240} />;
}

function Gone({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return error instanceof ApiError && error.status === 404 ? (
    <EmptyState title="Объект больше не существует" />
  ) : (
    <LoadError message={failureMessage(error)} onRetry={onRetry} />
  );
}

function TaskPanel({ chatId, created, card, draftRef }: CardPanelProps & { card: TaskCard }) {
  const client = useQueryClient();
  const afterSave = useAfterSave();
  const { data: user } = useCurrentUser();
  const { data: boards, isPending, refetch } = useBoards();
  const task = useTask(created ? chatId : undefined);
  // Bumped by "show the new version": the form rebuilds its draft from fresh data.
  const [revision, setRevision] = useState(0);
  const timeZone = user?.timezone ?? "UTC";

  const onDraftChange = useCallback(
    (draft: Draft, checklist: string[]) => {
      draftRef.current = draft.title.trim() ? cardFromTaskDraft(draft, checklist, timeZone) : null;
    },
    [draftRef, timeZone],
  );
  const onSaved = (saved: Draft) =>
    afterSave(created ? "Задача сохранена" : "Задача создана", `/boards/${saved.boardId}`);

  if (!user) return <Loading />;
  if (created) {
    if (!task.data) {
      return task.isPending ? (
        <Loading />
      ) : (
        <Gone error={task.error} onRetry={() => void task.refetch()} />
      );
    }
    const base = taskDraftOf(task.data, timeZone);
    return (
      <TaskForm
        key={revision}
        inline
        task={task.data}
        initial={base}
        proposed={taskProposedOnBase(card, base, timeZone)}
        timeZone={timeZone}
        removed={task.error instanceof ApiError && task.error.status === 404}
        submitLabel="Сохранить изменения"
        onClose={() => undefined}
        onReload={() => {
          void client.invalidateQueries({ queryKey: TASKS_KEY }).then(() => {
            setRevision((current) => current + 1);
          });
        }}
        onSaved={onSaved}
      />
    );
  }
  const personal = boards?.find((board) => board.is_default)?.id;
  if (!card.board_id && !personal) {
    return isPending ? <Loading /> : <LoadError onRetry={() => void refetch()} />;
  }
  return (
    <TaskForm
      inline
      newId={chatId}
      initial={taskDraftFromCard(card, timeZone, personal ?? "")}
      initialChecklist={card.checklist ?? []}
      timeZone={timeZone}
      submitLabel="Создать задачу"
      onClose={() => undefined}
      onReload={() => undefined}
      onDraftChange={onDraftChange}
      onSaved={onSaved}
    />
  );
}

function EventPanel({ chatId, created, card, draftRef }: CardPanelProps & { card: EventCard }) {
  const afterSave = useAfterSave();
  const { data: user } = useCurrentUser();
  const event = useEvent(created ? chatId : undefined);
  const timeZone = user?.timezone ?? "UTC";
  const meId = user?.id ?? "";

  const onDraftChange = useCallback(
    (draft: EventDraft) => {
      draftRef.current = cardFromEventDraft(draft, timeZone, meId);
    },
    [draftRef, timeZone, meId],
  );
  const onSaved = (saved: EventDraft) =>
    afterSave(
      created ? "Событие сохранено" : "Событие создано",
      `/calendar?day=${saved.startDate}`,
    );

  if (!user) return <Loading />;
  if (created) {
    if (!event.data) {
      return event.isPending ? (
        <Loading />
      ) : (
        <Gone error={event.error} onRetry={() => void event.refetch()} />
      );
    }
    const base = eventDraftOf(event.data, timeZone);
    return (
      <EventForm
        inline
        event={event.data}
        initial={base}
        proposed={eventProposedOnBase(card, base, timeZone, meId)}
        timeZone={timeZone}
        gone={event.error instanceof ApiError && event.error.status === 404}
        submitLabel="Сохранить изменения"
        onClose={() => undefined}
        onSaved={onSaved}
      />
    );
  }
  return (
    <EventForm
      inline
      newId={chatId}
      initial={eventDraftFromCard(card, timeZone, meId)}
      timeZone={timeZone}
      submitLabel="Создать событие"
      onClose={() => undefined}
      onDraftChange={onDraftChange}
      onSaved={onSaved}
    />
  );
}

export function CardPanel(props: CardPanelProps & { card: AssistantCard }) {
  const { card, ...rest } = props;
  return (
    <section className={styles.card} aria-label={card.kind === "task" ? "Задача" : "Событие"}>
      {card.kind === "task" ? (
        <TaskPanel {...rest} card={card} />
      ) : (
        <EventPanel {...rest} card={card} />
      )}
    </section>
  );
}
