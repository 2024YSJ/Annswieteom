import { useQuery } from "@tanstack/react-query";
import { sessionApi } from "./api-client";
import { useAuth } from "./auth-context";
import { queryKeys } from "./query-keys";

export function useSessionsList() {
  const { accessToken, isLoading: authLoading } = useAuth();

  return useQuery({
    queryKey: queryKeys.sessions(),
    queryFn: () => sessionApi.list(accessToken!),
    enabled: !authLoading && !!accessToken,
  });
}
