import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "../../api/client";
import { NOTIFICATIONS_KEY, SYNC_KEY } from "../../api/queryClient";

export function useNotifications(enabled: boolean) {
  return useInfiniteQuery({
    queryKey: NOTIFICATIONS_KEY,
    enabled,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/notifications", { params: { query: { cursor: pageParam } } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

function useRefreshAfterRead() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: NOTIFICATIONS_KEY }),
      client.invalidateQueries({ queryKey: SYNC_KEY }),
    ]);
}

export function useReadNotification() {
  const onSuccess = useRefreshAfterRead();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/notifications/{notification_id}/read", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess,
  });
}

export function useReadAllNotifications() {
  const onSuccess = useRefreshAfterRead();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/read-all")),
    onSuccess,
  });
}
