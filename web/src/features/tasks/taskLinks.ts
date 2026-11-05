import { useCallback } from "react";
import { useSearchParams } from "react-router";

/**
 * The task form lives in the URL, so it opens over any screen, a notification can lead to it,
 * and the back button closes it. `task` is an id or "new".
 */
const TASK_PARAM = "task";
const BOARD_PARAM = "board";
const COLUMN_PARAM = "column";
export const NEW_TASK = "new";

export function newTaskSearch(boardId?: string): string {
  const params = new URLSearchParams({ [TASK_PARAM]: NEW_TASK });
  if (boardId) params.set(BOARD_PARAM, boardId);
  return `?${params.toString()}`;
}

export function useTaskParam() {
  const [params, setParams] = useSearchParams();

  const open = useCallback(
    (task: string, boardId?: string, columnId?: string) => {
      setParams((current) => {
        current.set(TASK_PARAM, task);
        if (boardId) current.set(BOARD_PARAM, boardId);
        if (columnId) current.set(COLUMN_PARAM, columnId);
        return current;
      });
    },
    [setParams],
  );

  const close = useCallback(() => {
    setParams((current) => {
      current.delete(TASK_PARAM);
      current.delete(BOARD_PARAM);
      current.delete(COLUMN_PARAM);
      return current;
    });
  }, [setParams]);

  return {
    task: params.get(TASK_PARAM),
    boardId: params.get(BOARD_PARAM) ?? undefined,
    columnId: params.get(COLUMN_PARAM) ?? undefined,
    open,
    close,
  };
}
