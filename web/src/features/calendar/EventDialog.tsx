import { ApiError } from "../../api/client";
import { Banner, Dialog, EmptyState, Skeleton } from "../../ui";
import { useCurrentUser } from "../auth/session";
import { failureMessage } from "../tasks/api";
import { localDate } from "../tasks/dates";
import { useEvent } from "./api";
import { NEW_EVENT, useEventParam } from "./eventLinks";
import { EventForm, draftOf, newDraft } from "./EventForm";
import { EventView } from "./EventView";

function ExistingEvent({
  id,
  editing,
  onClose,
}: {
  id: string;
  editing: boolean;
  onClose: () => void;
}) {
  const { data: user } = useCurrentUser();
  const { data: event, error, isPending } = useEvent(id);
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
    return <EventView event={event} timeZone={user.timezone} onClose={onClose} />;
  }
  return (
    <Dialog title="Событие" width={640} onClose={onClose}>
      {isPending || !user ? (
        <Skeleton height={240} />
      ) : gone ? (
        <EmptyState title="Объект больше не существует" />
      ) : (
        <Banner tone="error">{failureMessage(error)}</Banner>
      )}
    </Dialog>
  );
}

/** Mounted once in the shell, so an event opens over whatever screen is underneath. */
export function EventDialogHost() {
  const { data: user } = useCurrentUser();
  const { event, editing, start, taskId, title, close } = useEventParam();
  if (!event) return null;
  if (event !== NEW_EVENT) {
    return <ExistingEvent key={event} id={event} editing={editing} onClose={close} />;
  }
  if (!user) return null;
  return (
    <EventForm
      initial={newDraft(
        user.id,
        start.day ?? localDate(new Date(), user.timezone),
        start.time,
        title,
      )}
      taskId={taskId}
      timeZone={user.timezone}
      onClose={close}
    />
  );
}
