import { useCallback } from "react";
import { useSearchParams } from "react-router";

/**
 * The event dialog lives in the URL, as the task form does: it opens over any screen, a
 * notification can lead to it, and the back button closes it. `event` is an id or "new".
 * `occurrence` names one repeat of a series: the id alone says only which series it is.
 */
const EVENT_PARAM = "event";
const EDIT_PARAM = "edit";
const OCCURRENCE_PARAM = "occurrence";
const START_PARAM = "start";
const TASK_PARAM = "for_task";
const TITLE_PARAM = "event_title";
const PARAMS = [EVENT_PARAM, EDIT_PARAM, OCCURRENCE_PARAM, START_PARAM, TASK_PARAM, TITLE_PARAM];
export const NEW_EVENT = "new";

/** What a new event starts from: a day, a day and a time, or the task it is planned for. */
export type NewEvent = { day?: string; time?: string; taskId?: string; title?: string };

export function useEventParam() {
  const [params, setParams] = useSearchParams();

  const open = useCallback(
    (id: string, occurrence?: string) => {
      setParams((current) => {
        current.set(EVENT_PARAM, id);
        current.delete(EDIT_PARAM);
        if (occurrence) current.set(OCCURRENCE_PARAM, occurrence);
        else current.delete(OCCURRENCE_PARAM);
        return current;
      });
    },
    [setParams],
  );

  const edit = useCallback(() => {
    setParams((current) => {
      current.set(EDIT_PARAM, "1");
      return current;
    });
  }, [setParams]);

  const create = useCallback(
    ({ day, time, taskId, title }: NewEvent = {}) => {
      setParams((current) => {
        current.set(EVENT_PARAM, NEW_EVENT);
        if (day) current.set(START_PARAM, time ? `${day}T${time}` : day);
        if (taskId) current.set(TASK_PARAM, taskId);
        if (title) current.set(TITLE_PARAM, title);
        return current;
      });
    },
    [setParams],
  );

  const close = useCallback(() => {
    setParams((current) => {
      for (const name of PARAMS) current.delete(name);
      return current;
    });
  }, [setParams]);

  /** In one step: two changes of the search params in a row would overwrite each other. */
  const switchToTask = useCallback(
    (taskId: string) => {
      setParams((current) => {
        for (const name of PARAMS) current.delete(name);
        current.set("task", taskId);
        return current;
      });
    },
    [setParams],
  );

  const [day, time] = (params.get(START_PARAM) ?? "").split("T");
  return {
    event: params.get(EVENT_PARAM),
    editing: params.has(EDIT_PARAM),
    occurrence: params.get(OCCURRENCE_PARAM) ?? undefined,
    start: { day: day || undefined, time },
    taskId: params.get(TASK_PARAM) ?? undefined,
    title: params.get(TITLE_PARAM) ?? undefined,
    open,
    edit,
    create,
    close,
    switchToTask,
  };
}
