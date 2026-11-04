import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api, unwrap, type SyncState } from "../../api/client";
import { BOARDS_KEY, NOTIFICATIONS_KEY, SYNC_KEY, TASKS_KEY } from "../../api/queryClient";
import { whenReleased } from "./hold";

const POLL_MS = 5_000;

/**
 * The counters only say that something changed, the screens then reread what they show.
 * React Query stops the interval in a hidden tab and refetches on return to it.
 */
export function useSync() {
  const client = useQueryClient();
  const seen = useRef<SyncState | undefined>(undefined);
  const { data, isError } = useQuery({
    queryKey: SYNC_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/sync")),
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: "always",
    staleTime: 0,
    retry: false, // The next tick is the retry.
  });

  useEffect(() => {
    if (!data) return;
    const before = seen.current;
    seen.current = data;
    if (!before) return;
    if (before.tasks !== data.tasks) {
      whenReleased(() => {
        void client.invalidateQueries({ queryKey: TASKS_KEY });
        void client.invalidateQueries({ queryKey: BOARDS_KEY });
      });
    }
    if (before.notifications !== data.notifications) {
      void client.invalidateQueries({ queryKey: NOTIFICATIONS_KEY });
    }
  }, [client, data]);

  return { unread: data?.unread_notifications ?? 0, disconnected: isError };
}
