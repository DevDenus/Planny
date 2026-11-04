import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api, unwrap, type Board, type BoardRole } from "../../api/client";
import { BOARDS_KEY, TASKS_KEY } from "../../api/queryClient";
import type { components } from "../../api/schema";

type BoardCreate = components["schemas"]["BoardCreate"];
type BoardUpdate = components["schemas"]["BoardUpdate"];

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

export function useColumns(boardId: string | undefined) {
  return useQuery({
    queryKey: [...BOARDS_KEY, "columns", boardId],
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
