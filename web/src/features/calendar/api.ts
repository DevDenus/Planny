import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import {
  api,
  unwrap,
  type CalendarItem,
  type CategoryCreate,
  type CategoryUpdate,
  type EventCreate,
  type EventUpdate,
  type TaskFilters,
} from "../../api/client";
import { BOARDS_KEY, CALENDAR_KEY, TASKS_KEY } from "../../api/queryClient";
import { useToast } from "../../ui";
import { failureMessage } from "../tasks/api";

const ITEMS_KEY = [...CALENDAR_KEY, "items"] as const;
const CATEGORIES_KEY = [...CALENDAR_KEY, "categories"] as const;
const AVAILABILITY_KEY = [...CALENDAR_KEY, "availability"] as const;
const SEARCH_KEY = [...CALENDAR_KEY, "search"] as const;

type Period = { from: string; to: string };

const eventPath = (id: string) => ({ params: { path: { event_id: id } } });
const categoryPath = (id: string) => ({ params: { path: { category_id: id } } });
const eventKey = (id: string) => [...CALENDAR_KEY, "event", id] as const;

function refresh(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: CALENDAR_KEY }),
    client.invalidateQueries({ queryKey: [...TASKS_KEY, "detail"] }),
  ]);
}

export function useCalendarItems(
  period: Period,
  boardId?: string,
  filters: Pick<TaskFilters, "assignee" | "label_id"> = {},
) {
  return useQuery({
    queryKey: [...ITEMS_KEY, period.from, period.to, boardId ?? null, filters],
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/v1/calendar/items", {
            params: { query: { ...period, ...(boardId && { board_id: boardId }), ...filters } },
          }),
        )
      ).items as CalendarItem[],
    // The previous period stays on screen until the next one arrives, so the grid doesn't blink.
    placeholderData: keepPreviousData,
  });
}

export function useEvent(id: string | undefined) {
  return useQuery({
    queryKey: eventKey(id ?? ""),
    enabled: id !== undefined,
    // A cached copy would let an event deleted meanwhile reopen as an editable form, not as gone.
    gcTime: 0,
    queryFn: () => unwrap(api.GET("/api/v1/events/{event_id}", eventPath(id as string))),
  });
}

export function useCreateEvent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: EventCreate) => unwrap(api.POST("/api/v1/events", { body })),
    onSuccess: () => refresh(client),
  });
}

export function useUpdateEvent(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: EventUpdate) =>
      unwrap(api.PATCH("/api/v1/events/{event_id}", { ...eventPath(id), body })),
    onSuccess: () => refresh(client),
  });
}

export function useDeleteEvent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/events/{event_id}", eventPath(id))),
    onSuccess: () => refresh(client),
  });
}

export function useLeaveEvent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/events/{event_id}/participants/me", eventPath(id))),
    onSuccess: () => refresh(client),
  });
}

/** Done right from the calendar. The grid answers at once, as the checkboxes on other screens. */
export function useToggleDeadline() {
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) => {
      const path = { params: { path: { task_id: id } } };
      return unwrap(
        done
          ? api.POST("/api/v1/tasks/{task_id}/complete", path)
          : api.POST("/api/v1/tasks/{task_id}/reopen", path),
      );
    },
    onMutate: async ({ id, done }) => {
      await client.cancelQueries({ queryKey: ITEMS_KEY });
      const snapshot = client.getQueriesData<CalendarItem[]>({ queryKey: ITEMS_KEY });
      client.setQueriesData<CalendarItem[]>({ queryKey: ITEMS_KEY }, (items) =>
        items?.map((item) =>
          item.type === "task" && item.task_id === id
            ? { ...item, completed_at: done ? new Date().toISOString() : null }
            : item,
        ),
      );
      return { snapshot };
    },
    onError: (error, _, context) => {
      for (const [key, data] of context?.snapshot ?? []) client.setQueryData(key, data);
      toast.show(failureMessage(error), "error");
    },
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: CALENDAR_KEY }),
        client.invalidateQueries({ queryKey: TASKS_KEY }),
        client.invalidateQueries({ queryKey: BOARDS_KEY }),
      ]),
  });
}

export function useCategories() {
  return useQuery({
    queryKey: CATEGORIES_KEY,
    queryFn: async () => (await unwrap(api.GET("/api/v1/categories"))).items,
  });
}

export function useCreateCategory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: CategoryCreate) => unwrap(api.POST("/api/v1/categories", { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: CATEGORIES_KEY }),
  });
}

export function useUpdateCategory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CategoryUpdate }) =>
      unwrap(api.PATCH("/api/v1/categories/{category_id}", { ...categoryPath(id), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: CATEGORIES_KEY }),
  });
}

export function useDeleteCategory() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/categories/{category_id}", categoryPath(id))),
    // Events lose the category, so the whole calendar is reread.
    onSuccess: () => refresh(client),
  });
}

export function useAvailability(
  userIds: string[],
  period: Period | null,
  excludeEventId: string | undefined,
) {
  return useQuery({
    queryKey: [...AVAILABILITY_KEY, userIds, period, excludeEventId ?? null],
    enabled: userIds.length > 0 && period !== null,
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (
        await unwrap(
          api.GET("/api/v1/availability", {
            params: {
              query: {
                ...(period as Period),
                user_ids: userIds,
                ...(excludeEventId && { exclude_event_id: excludeEventId }),
              },
            },
          }),
        )
      ).items,
  });
}

export function useSearch(query: string) {
  return useQuery({
    queryKey: [...SEARCH_KEY, query],
    enabled: query.length > 0,
    placeholderData: keepPreviousData,
    queryFn: () => unwrap(api.GET("/api/v1/search", { params: { query: { q: query } } })),
  });
}

export function useLinkEvent(taskId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (eventId: string) =>
      unwrap(
        api.POST("/api/v1/tasks/{task_id}/event-links", {
          params: { path: { task_id: taskId } },
          body: { event_id: eventId },
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

export function useUnlinkEvent(taskId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (eventId: string) =>
      unwrap(
        api.DELETE("/api/v1/tasks/{task_id}/event-links/{event_id}", {
          params: { path: { task_id: taskId, event_id: eventId } },
        }),
      ),
    onSuccess: () => refresh(client),
  });
}
