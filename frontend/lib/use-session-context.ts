import { useQuery } from "@tanstack/react-query";
import { sessionApi } from "./api-client";
import { useAuth } from "./auth-context";
import { queryKeys } from "./query-keys";

export function useSessionContext(sessionId: string) {
  const { accessToken, isLoading: authLoading } = useAuth();

  return useQuery({
    queryKey: queryKeys.session(sessionId),
    queryFn: () => sessionApi.get(sessionId, accessToken!),
    enabled: !authLoading && !!accessToken,
  });
}
