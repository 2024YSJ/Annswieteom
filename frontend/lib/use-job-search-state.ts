import { useQuery } from "@tanstack/react-query";
import { jobSearchApi } from "./api-client";
import { useAuth } from "./auth-context";
import { queryKeys } from "./query-keys";

// Same timeout-race reasoning as useSessionContext — a stalled fetch must
// still settle so the job-search page doesn't hang on "불러오는 중" forever.
const JOB_SEARCH_FETCH_TIMEOUT_MS = 65000;

export function useJobSearchState(sessionId: string) {
  const { accessToken, isLoading: authLoading } = useAuth();

  return useQuery({
    queryKey: queryKeys.jobSearch(sessionId),
    queryFn: () => {
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("job_search_fetch_timeout")), JOB_SEARCH_FETCH_TIMEOUT_MS),
      );
      return Promise.race([jobSearchApi.getState(sessionId, accessToken!), timeout]);
    },
    enabled: !authLoading && !!accessToken,
  });
}
