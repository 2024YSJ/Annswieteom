import { useQuery } from "@tanstack/react-query";
import { sessionApi } from "./api-client";
import { useAuth } from "./auth-context";
import { queryKeys } from "./query-keys";

// `fetch` has no default timeout, so a request that stalls (rather than
// cleanly failing) never resolves — react-query's own retry/error handling
// can't kick in for a promise that hasn't rejected yet, which would leave
// the session page's loading screen up indefinitely. Racing against a
// timeout guarantees this query eventually settles one way or the other
// (react-query's default retry then applies normally on top of that).
//
// Must stay above Render free-tier's real cold-start ceiling (LoadingNotice
// documents "최대 1분") — a shorter timeout here doesn't just show an error
// sooner, it actively misfires *while the real request would have
// succeeded*. For this query, that means clobbering session state with a
// stale-error re-render mid-cold-start (production, 2026-09-05).
const SESSION_FETCH_TIMEOUT_MS = 65000;

export function useSessionContext(sessionId: string, enabled = true) {
  const { accessToken, isLoading: authLoading } = useAuth();

  return useQuery({
    queryKey: queryKeys.session(sessionId),
    queryFn: () => {
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("session_fetch_timeout")), SESSION_FETCH_TIMEOUT_MS),
      );
      return Promise.race([sessionApi.get(sessionId, accessToken!), timeout]);
    },
    enabled: enabled && !authLoading && !!accessToken,
  });
}
