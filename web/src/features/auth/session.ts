import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, login, logout, unwrap } from "../../api/client";
import { ME_KEY } from "../../api/queryClient";

export function useCurrentUser() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/me")),
  });
}

export function useSession() {
  const { data, error, isPending, refetch } = useCurrentUser();
  // React Query keeps the last data after a failed refetch, so data alone proves nothing.
  const signedOut = error instanceof ApiError && error.status === 401;
  // A user who was here and got a 401 lost the session: logging out clears the cache first.
  const expired = signedOut && data !== undefined;
  return { user: signedOut ? undefined : data, signedOut, expired, isPending, refetch };
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: login,
    onSuccess: () => {
      // A session can end without a logout, and then the next person signs in over the cache of
      // the last one. A plain clear() would leave this screen unaware of the new /me.
      client.removeQueries({ predicate: ({ queryKey }) => queryKey[0] !== ME_KEY[0] });
      // Reset, not invalidate: an earlier 401 must not be read as the current state.
      return client.resetQueries({ queryKey: ME_KEY });
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: logout,
    // Nothing of this user may stay in memory for the next person at this browser.
    onSuccess: () => client.clear(),
  });
}

export function useChangePassword() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { current_password?: string; new_password: string }) =>
      unwrap(api.POST("/api/v1/auth/change-password", { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: ME_KEY }),
  });
}
