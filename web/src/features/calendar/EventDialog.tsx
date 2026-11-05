import { ApiError } from "../../api/client";
import { Dialog, EmptyState, LoadError, Skeleton } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { failureMessage, useTask } from "../tasks/api";
import { localDate } from "../tasks/dates";
import { useEvent } from "./api";
import { NEW_EVENT, useEventParam } from "./eventLinks";
import { EventForm, draftOf, newDraft } from "./EventForm";
import { EventView } from "./EventView";

function ExistingEvent({
  id,
  editing,
  occurrence,
  onClose,
}: {
  id: string;
  editing: boolean;
  occurrence?: string;
  onClose: () => void;
}) {
  const { data: user } = useCurrentUser();
  const { data: event, error, isPending, refetch } = useEvent(id);
  // A failed refetch keeps the last data next to its error, so the 404 is read from the error.
  const gone = error instanceof ApiError && error.status === 404;

  if (event && user && editing) {
    return (
      <EventForm
        event={event}
        initial={draftOf(event, user.timezone)}
        timeZone={user.timezone}
        gone={gone}
        onClose={onClose}
      />
    );
  }
  if (event && user && !gone) {
    return (
      <EventView event={event} occurrence={occurrence} timeZone={user.timezone} onClose={onClose} />
    );
  }
  return (
    <Dialog title="Событие" width={640} onClose={onClose}>
      {isPending || !user ? (
        <Skeleton height={240} />
      ) : gone ? (
        <EmptyState title="Объект больше не существует" />
      ) : (
        <LoadError message={failureMessage(error)} onRetry={() => void refetch()} />
      )}
    </Dialog>
  );
}

type NewEventDialogProps = {
  day?: string;
  time?: string;
  /** The task the event is planned for: its title comes from the server, for this user. */
  taskId?: string;
  onClose: () => void;
};

function NewEventDialog({ day, time, taskId, onClose }: NewEventDialogProps) {
  const { data: user } = useCurrentUser();
  const { data: task, error, isPending, refetch } = useTask(taskId);

  if (!user) return null;
  if (taskId && !task) {
    return (
      <Dialog title="Новое событие" width={640} onClose={onClose}>
        {isPending ? (
          <Skeleton height={240} />
        ) : error instanceof ApiError && error.status === 404 ? (
          <EmptyState title="Объект больше не существует" />
        ) : (
          <LoadError message={failureMessage(error)} onRetry={() => void refetch()} />
        )}
      </Dialog>
    );
  }
  return (
    <EventForm
      initial={newDraft(user.id, day ?? localDate(new Date(), user.timezone), time, task?.title)}
      taskId={taskId}
      timeZone={user.timezone}
      onClose={onClose}
    />
  );
}

/** Mounted once in the shell, so an event opens over whatever screen is underneath. */
export function EventDialogHost() {
  const { event, editing, occurrence, start, taskId, close } = useEventParam();
  if (!event) return null;
  if (event !== NEW_EVENT) {
    return (
      <ExistingEvent
        key={event}
        id={event}
        editing={editing}
        occurrence={occurrence}
        onClose={close}
      />
    );
  }
  return <NewEventDialog day={start.day} time={start.time} taskId={taskId} onClose={close} />;
}
