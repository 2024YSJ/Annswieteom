import { useQuery } from "@tanstack/react-query";
import { sessionApi } from "./api-client";
import { useAuth } from "./auth-context";
import { queryKeys } from "./query-keys";

// See use-session-context.ts for why this races against a timeout: a
// stalled (not cleanly failed) fetch never resolves on its own, and the
// home page's auto-redirect effect waits on this query before it can act —
// without a bound here, a stalled request leaves the visitor stuck on the
// loading screen indefinitely instead of falling through to a usable state.
const SESSIONS_FETCH_TIMEOUT_MS = 15000;

export function useSessionsList() {
  const { accessToken, isLoading: authLoading } = useAuth();

  return useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => {
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("sessions_fetch_timeout")), SESSIONS_FETCH_TIMEOUT_MS),
      );
      return Promise.race([sessionApi.list(accessToken!), timeout]);
    },
    enabled: !authLoading && !!accessToken,
  });
}
