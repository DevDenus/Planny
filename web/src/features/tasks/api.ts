import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";

import {
  ApiError,
  api,
  unwrap,
  type ChecklistItem,
  type Task,
  type TaskActivityPage,
  type TaskCommentPage,
  type TaskCreate,
  type TaskFilters,
  type TaskPage,
  type TaskSummary,
  type TaskUpdate,
} from "../../api/client";
import { BOARDS_KEY, TASKS_KEY } from "../../api/queryClient";
import { useToast } from "../../ui";

const LISTS_KEY = [...TASKS_KEY, "list"] as const;
const SAVE_FAILED = "Не удалось сохранить. Попробуйте ещё раз";

type Pages = InfiniteData<TaskPage, string | undefined>;
type Snapshot = [readonly unknown[], Pages | undefined][];

const taskPath = (id: string) => ({ params: { path: { task_id: id } } });
const detailKey = (id: string) => [...TASKS_KEY, "detail", id] as const;

export function failureMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : SAVE_FAILED;
}

function refresh(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: TASKS_KEY }),
    client.invalidateQueries({ queryKey: BOARDS_KEY }),
  ]);
}

export function useTaskList(filters: TaskFilters, enabled = true) {
  return useInfiniteQuery({
    queryKey: [...LISTS_KEY, filters],
    enabled,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/tasks", { params: { query: { ...filters, cursor: pageParam } } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useTask(id: string | undefined) {
  return useQuery({
    queryKey: detailKey(id ?? ""),
    enabled: id !== undefined,
    // A cached copy would let a task deleted meanwhile reopen as an editable form, not as gone.
    gcTime: 0,
    queryFn: () => unwrap(api.GET("/api/v1/tasks/{task_id}", taskPath(id as string))),
  });
}

function updateInLists(client: QueryClient, id: string, change: Partial<TaskSummary>) {
  for (const [key, data] of client.getQueriesData<Pages>({ queryKey: LISTS_KEY })) {
    if (!data) continue;
    client.setQueryData<Pages>(key, {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((item) => (item.id === id ? { ...item, ...change } : item)),
      })),
    });
  }
}

function appendToLists(
  client: QueryClient,
  task: TaskSummary,
  showsIn: (filters: TaskFilters) => boolean,
) {
  for (const [key, data] of client.getQueriesData<Pages>({ queryKey: LISTS_KEY })) {
    // The filters of a list are the last part of its key.
    if (!data || !showsIn(key.at(-1) as TaskFilters)) continue;
    const last = data.pages.length - 1;
    client.setQueryData<Pages>(key, {
      ...data,
      pages: data.pages.map((page, index) =>
        index === last ? { ...page, items: [...page.items, task] } : page,
      ),
    });
  }
}

async function beginOptimistic(client: QueryClient): Promise<Snapshot> {
  await client.cancelQueries({ queryKey: LISTS_KEY });
  return client.getQueriesData<Pages>({ queryKey: LISTS_KEY });
}

function rollback(client: QueryClient, snapshot: Snapshot | undefined) {
  for (const [key, data] of snapshot ?? []) client.setQueryData(key, data);
}

export function useToggleDone() {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) =>
      unwrap(
        done
          ? api.POST("/api/v1/tasks/{task_id}/complete", taskPath(id))
          : api.POST("/api/v1/tasks/{task_id}/reopen", taskPath(id)),
      ),
    onMutate: async ({ id, done }) => {
      const snapshot = await beginOptimistic(client);
      updateInLists(client, id, { completed_at: done ? new Date().toISOString() : null });
      return { snapshot };
    },
    onError: (error, _, context) => {
      rollback(client, context?.snapshot);
      toast.show(failureMessage(error), "error");
    },
    onSettled: () => refresh(client),
  });
}

export type QuickAddTarget = {
  boardId: string;
  boardName: string;
  columnId?: string;
  /** Which of the cached lists the new card belongs to. */
  showsIn: (filters: TaskFilters) => boolean;
};

export function useQuickAdd() {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ id, title, target }: { id: string; title: string; target: QuickAddTarget }) =>
      unwrap(
        api.POST("/api/v1/tasks", {
          body: { id, title, board_id: target.boardId, column_id: target.columnId, priority: 3 },
        }),
      ),
    onMutate: async ({ id, title, target }) => {
      const snapshot = await beginOptimistic(client);
      const draft: TaskSummary = {
        id,
        title,
        board_id: target.boardId,
        board_name: target.boardName,
        column_id: target.columnId ?? "",
        priority: 3,
        position: "",
        start_date: null,
        due_date: null,
        due_at: null,
        completed_at: null,
        assignees: [],
        labels: [],
        checklist_total: 0,
        checklist_done: 0,
        comments_count: 0,
        updated_at: new Date().toISOString(),
      };
      appendToLists(client, draft, target.showsIn);
      return { snapshot };
    },
    onError: (error, _, context) => {
      rollback(client, context?.snapshot);
      toast.show(failureMessage(error), "error");
    },
    onSettled: () => refresh(client),
  });
}

export function useCreateTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: TaskCreate) => unwrap(api.POST("/api/v1/tasks", { body })),
    onSuccess: () => refresh(client),
  });
}

export function useUpdateTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: TaskUpdate }) =>
      unwrap(api.PATCH("/api/v1/tasks/{task_id}", { ...taskPath(id), body })),
    onSuccess: () => refresh(client),
  });
}

export function useMoveTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, columnId, afterId }: MoveInput) =>
      unwrap(
        api.POST("/api/v1/tasks/{task_id}/move", {
          ...taskPath(id),
          body: { column_id: columnId, after_id: afterId },
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

type MoveInput = { id: string; columnId: string; afterId: string | null };

/** The lists of a board are one per column, and the others only learn the new status. */
function placeInLists(client: QueryClient, task: TaskSummary, afterId: string | null | undefined) {
  for (const [key, data] of client.getQueriesData<Pages>({ queryKey: LISTS_KEY })) {
    if (!data) continue;
    const { column_id: columnId } = key.at(-1) as TaskFilters;
    const pages = data.pages.map((page) => ({
      ...page,
      items:
        columnId === undefined
          ? page.items.map((item) => (item.id === task.id ? task : item))
          : page.items.filter((item) => item.id !== task.id),
    }));
    if (columnId === task.column_id) {
      const place = pages.findIndex((page) => page.items.some((item) => item.id === afterId));
      // An anchor that isn't loaded means the end, as on the server.
      const index = afterId === null ? 0 : place >= 0 ? place : pages.length - 1;
      const page = pages[index];
      if (page) {
        const at = afterId === null ? 0 : page.items.findIndex((item) => item.id === afterId) + 1;
        const end = place >= 0 || afterId === null ? at : page.items.length;
        pages[index] = {
          ...page,
          items: [...page.items.slice(0, end), task, ...page.items.slice(end)],
        };
      }
    }
    client.setQueryData<Pages>(key, { ...data, pages });
  }
}

export type CardMove = {
  /** The card as it is now, drawn at the new place until the server answers. */
  task: TaskSummary;
  columnId: string;
  columnIsDone: boolean;
  /** Null is the start of the column, undefined the end. */
  afterId: string | null | undefined;
};

const CARD_MOVE_KEY = ["move-card"] as const;

/**
 * For drags, where the move has to show at once. The refresh waits for the last of several
 * quick moves, otherwise an older answer would put a card back for a moment.
 */
export function useMoveCard() {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationKey: CARD_MOVE_KEY,
    mutationFn: ({ task, columnId, afterId }: CardMove) =>
      unwrap(
        api.POST("/api/v1/tasks/{task_id}/move", {
          ...taskPath(task.id),
          body: { column_id: columnId, after_id: afterId },
        }),
      ),
    onMutate: async ({ task, columnId, columnIsDone, afterId }) => {
      const snapshot = await beginOptimistic(client);
      const completedAt = columnIsDone ? (task.completed_at ?? new Date().toISOString()) : null;
      placeInLists(client, { ...task, column_id: columnId, completed_at: completedAt }, afterId);
      return { snapshot };
    },
    onError: (error, _, context) => {
      rollback(client, context?.snapshot);
      toast.show(
        error instanceof ApiError && error.status < 500
          ? error.message
          : "Не удалось перенести карточку",
        "error",
      );
    },
    onSettled: () =>
      client.isMutating({ mutationKey: CARD_MOVE_KEY }) === 1 ? refresh(client) : undefined,
  });
}

export function useDeleteTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/tasks/{task_id}", taskPath(id))),
    onSuccess: () => refresh(client),
  });
}

// Comments and history. Both grow from the side of the newest record.

const commentsKey = (taskId: string) => [...TASKS_KEY, "comments", taskId] as const;
const commentPath = (taskId: string, commentId: string) => ({
  params: { path: { task_id: taskId, comment_id: commentId } },
});

export function useComments(taskId: string) {
  return useInfiniteQuery({
    queryKey: commentsKey(taskId),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }): Promise<TaskCommentPage> =>
      unwrap(
        api.GET("/api/v1/tasks/{task_id}/comments", {
          params: { path: { task_id: taskId }, query: { cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useActivity(taskId: string) {
  return useInfiniteQuery({
    queryKey: [...TASKS_KEY, "activity", taskId],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }): Promise<TaskActivityPage> =>
      unwrap(
        api.GET("/api/v1/tasks/{task_id}/activity", {
          params: { path: { task_id: taskId }, query: { cursor: pageParam } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useAddComment(taskId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { id: string; body: string }) =>
      unwrap(api.POST("/api/v1/tasks/{task_id}/comments", { ...taskPath(taskId), body })),
    onSuccess: () => refresh(client),
  });
}

export function useUpdateComment(taskId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ commentId, body }: { commentId: string; body: string }) =>
      unwrap(
        api.PATCH("/api/v1/tasks/{task_id}/comments/{comment_id}", {
          ...commentPath(taskId, commentId),
          body: { body },
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

export function useDeleteComment(taskId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (commentId: string) =>
      unwrap(
        api.DELETE("/api/v1/tasks/{task_id}/comments/{comment_id}", commentPath(taskId, commentId)),
      ),
    onSuccess: () => refresh(client),
  });
}

// Checklist. Each change applies at once, independently of the form it sits in.

const itemPath = (taskId: string, itemId: string) => ({
  params: { path: { task_id: taskId, item_id: itemId } },
});

function useChecklistMutation<Input>(
  taskId: string,
  mutationFn: (input: Input) => Promise<unknown>,
  optimistic?: (items: ChecklistItem[], input: Input) => ChecklistItem[],
) {
  const client = useQueryClient();
  const toast = useToast();
  const key = detailKey(taskId);
  return useMutation({
    mutationFn,
    onMutate: async (input: Input) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Task>(key);
      if (previous && optimistic) {
        client.setQueryData<Task>(key, {
          ...previous,
          checklist: optimistic(previous.checklist, input),
        });
      }
      return { previous };
    },
    onError: (error, _, context) => {
      if (context?.previous) client.setQueryData(key, context.previous);
      toast.show(failureMessage(error), "error");
    },
    onSettled: () => refresh(client),
  });
}

export function useAddChecklistItem(taskId: string) {
  return useChecklistMutation(taskId, (text: string) =>
    unwrap(api.POST("/api/v1/tasks/{task_id}/checklist", { ...taskPath(taskId), body: { text } })),
  );
}

export function useToggleChecklistItem(taskId: string) {
  return useChecklistMutation(
    taskId,
    ({ itemId, done }: { itemId: string; done: boolean }) =>
      unwrap(
        api.PATCH("/api/v1/tasks/{task_id}/checklist/{item_id}", {
          ...itemPath(taskId, itemId),
          body: { is_done: done },
        }),
      ),
    (items, { itemId, done }) =>
      items.map((item) => (item.id === itemId ? { ...item, is_done: done } : item)),
  );
}

export function useMoveChecklistItem(taskId: string) {
  return useChecklistMutation(
    taskId,
    ({ itemId, afterId }: { itemId: string; afterId: string | null }) =>
      unwrap(
        api.PATCH("/api/v1/tasks/{task_id}/checklist/{item_id}", {
          ...itemPath(taskId, itemId),
          body: { after_id: afterId },
        }),
      ),
    (items, { itemId, afterId }) => {
      const moved = items.find((item) => item.id === itemId);
      if (!moved) return items;
      const rest = items.filter((item) => item.id !== itemId);
      const index = afterId === null ? 0 : rest.findIndex((item) => item.id === afterId) + 1;
      return [...rest.slice(0, index), moved, ...rest.slice(index)];
    },
  );
}

export function useDeleteChecklistItem(taskId: string) {
  return useChecklistMutation(
    taskId,
    (itemId: string) =>
      unwrap(api.DELETE("/api/v1/tasks/{task_id}/checklist/{item_id}", itemPath(taskId, itemId))),
    (items, itemId) => items.filter((item) => item.id !== itemId),
  );
}
