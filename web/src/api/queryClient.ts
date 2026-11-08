import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

export const ME_KEY = ["me"] as const;
export const SYNC_KEY = ["sync"] as const;
export const BOARDS_KEY = ["boards"] as const;
export const TASKS_KEY = ["tasks"] as const;
export const CALENDAR_KEY = ["calendar"] as const;
export const ASSISTANT_KEY = ["assistant"] as const;
export const NOTIFICATIONS_KEY = ["notifications"] as const;

const SESSION_ERRORS = new Set(["unauthorized", "password_change_required"]);

/** Any request can learn that the session ended, the session guard then redirects. */
function recheckSession(error: unknown): void {
  if (error instanceof ApiError && SESSION_ERRORS.has(error.code)) {
    void queryClient.invalidateQueries({ queryKey: ME_KEY });
  }
}

export const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    // Skipping "me" itself: rechecking it after its own failure would loop forever.
    onError: (error, query) => {
      if (query.queryKey[0] !== ME_KEY[0]) recheckSession(error);
    },
  }),
  mutationCache: new MutationCache({ onError: recheckSession }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failures, error) =>
        !(error instanceof ApiError && error.status < 500) && failures < 2,
    },
  },
});
