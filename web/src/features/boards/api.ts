import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import {
  api,
  unwrap,
  type Board,
  type BoardColumn,
  type BoardRole,
  type Label,
  type LabelColor,
} from "../../api/client";
import { BOARDS_KEY, TASKS_KEY } from "../../api/queryClient";
import type { components } from "../../api/schema";
import { useToast } from "../../ui";

type BoardCreate = components["schemas"]["BoardCreate"];
type BoardUpdate = components["schemas"]["BoardUpdate"];
type ColumnCreate = components["schemas"]["BoardColumnCreate"];
type ColumnUpdate = components["schemas"]["BoardColumnUpdate"];

const boardPath = (id: string) => ({ params: { path: { board_id: id } } });

/** Cards show board names and boards show card counts, so one change touches both. */
function refresh(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: BOARDS_KEY }),
    client.invalidateQueries({ queryKey: TASKS_KEY }),
  ]);
}

export function useBoards(archived = false) {
  return useQuery({
    queryKey: [...BOARDS_KEY, "list", { archived }],
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/boards", { params: { query: { archived } } }))).items,
  });
}

export function useBoard(id: string | undefined) {
  return useQuery({
    queryKey: [...BOARDS_KEY, "detail", id],
    enabled: id !== undefined,
    queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}", boardPath(id as string))),
  });
}

const columnsKey = (boardId: string | undefined) => [...BOARDS_KEY, "columns", boardId] as const;
const labelsKey = (boardId: string | undefined) => [...BOARDS_KEY, "labels", boardId] as const;

export function useColumns(boardId: string | undefined) {
  return useQuery({
    queryKey: columnsKey(boardId),
    enabled: boardId !== undefined,
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/boards/{board_id}/columns", boardPath(boardId as string))))
        .items,
  });
}

export function useMembers(boardId: string | undefined) {
  return useQuery({
    queryKey: [...BOARDS_KEY, "members", boardId],
    enabled: boardId !== undefined,
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/boards/{board_id}/members", boardPath(boardId as string))))
        .items,
  });
}

export function useUsers(enabled: boolean) {
  return useQuery({
    queryKey: ["users"],
    enabled,
    queryFn: async () => (await unwrap(api.GET("/api/v1/users"))).items,
  });
}

export function useCreateBoard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: BoardCreate) => unwrap(api.POST("/api/v1/boards", { body })),
    onSuccess: () => refresh(client),
  });
}

export function useUpdateBoard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: BoardUpdate }): Promise<Board> =>
      unwrap(api.PATCH("/api/v1/boards/{board_id}", { ...boardPath(id), body })),
    // Settled, not success: after a version conflict the dialog offers the fresh version.
    onSettled: () => refresh(client),
  });
}

export function useAddMember(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { user_id: string; role: BoardRole }) =>
      unwrap(api.POST("/api/v1/boards/{board_id}/members", { ...boardPath(boardId), body })),
    onSuccess: () => refresh(client),
  });
}

const memberPath = (boardId: string, userId: string) => ({
  params: { path: { board_id: boardId, user_id: userId } },
});

export function useUpdateMember(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: BoardRole }) =>
      unwrap(
        api.PATCH("/api/v1/boards/{board_id}/members/{user_id}", {
          ...memberPath(boardId, userId),
          body: { role },
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

export function useRemoveMember(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.DELETE("/api/v1/boards/{board_id}/members/{user_id}", memberPath(boardId, userId)),
      ),
    onSuccess: () => refresh(client),
  });
}

// Columns

const columnPath = (boardId: string, columnId: string) => ({
  params: { path: { board_id: boardId, column_id: columnId } },
});

export function useCreateColumn(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ColumnCreate) =>
      unwrap(api.POST("/api/v1/boards/{board_id}/columns", { ...boardPath(boardId), body })),
    onSuccess: () => refresh(client),
  });
}

export function useUpdateColumn(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ columnId, body }: { columnId: string; body: ColumnUpdate }) =>
      unwrap(
        api.PATCH("/api/v1/boards/{board_id}/columns/{column_id}", {
          ...columnPath(boardId, columnId),
          body,
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

function placeColumn(
  columns: BoardColumn[],
  columnId: string,
  afterId: string | null,
): BoardColumn[] {
  const moved = columns.find((column) => column.id === columnId);
  if (!moved) return columns;
  const rest = columns.filter((column) => column.id !== columnId);
  const index = afterId === null ? 0 : rest.findIndex((column) => column.id === afterId) + 1;
  return [...rest.slice(0, index), moved, ...rest.slice(index)];
}

export function useMoveColumn(boardId: string) {
  const client = useQueryClient();
  const toast = useToast();
  const key = columnsKey(boardId);
  return useMutation({
    mutationFn: ({ columnId, afterId }: { columnId: string; afterId: string | null }) =>
      unwrap(
        api.POST("/api/v1/boards/{board_id}/columns/{column_id}/move", {
          ...columnPath(boardId, columnId),
          body: { after_id: afterId },
        }),
      ),
    onMutate: async ({ columnId, afterId }) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<BoardColumn[]>(key);
      if (previous) client.setQueryData(key, placeColumn(previous, columnId, afterId));
      return { previous };
    },
    onError: (_, __, context) => {
      if (context?.previous) client.setQueryData(key, context.previous);
      toast.show("Не удалось перенести колонку", "error");
    },
    onSettled: () => refresh(client),
  });
}

export function useDeleteColumn(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ columnId, moveTo }: { columnId: string; moveTo?: string }) =>
      unwrap(
        api.DELETE("/api/v1/boards/{board_id}/columns/{column_id}", {
          params: {
            path: { board_id: boardId, column_id: columnId },
            query: { move_to: moveTo },
          },
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

// Labels

const labelPath = (boardId: string, labelId: string) => ({
  params: { path: { board_id: boardId, label_id: labelId } },
});

export function useLabels(boardId: string | undefined) {
  return useQuery({
    queryKey: labelsKey(boardId),
    enabled: boardId !== undefined,
    queryFn: async () =>
      (await unwrap(api.GET("/api/v1/boards/{board_id}/labels", boardPath(boardId as string))))
        .items,
  });
}

export function useCreateLabel(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; color: LabelColor }): Promise<Label> =>
      unwrap(api.POST("/api/v1/boards/{board_id}/labels", { ...boardPath(boardId), body })),
    onSuccess: () => refresh(client),
  });
}

export function useUpdateLabel(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ labelId, ...body }: { labelId: string; name: string; color: LabelColor }) =>
      unwrap(
        api.PATCH("/api/v1/boards/{board_id}/labels/{label_id}", {
          ...labelPath(boardId, labelId),
          body,
        }),
      ),
    onSuccess: () => refresh(client),
  });
}

export function useDeleteLabel(boardId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (labelId: string) =>
      unwrap(
        api.DELETE("/api/v1/boards/{board_id}/labels/{label_id}", labelPath(boardId, labelId)),
      ),
    onSuccess: () => refresh(client),
  });
}
