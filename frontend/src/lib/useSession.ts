import { useQuery } from "@tanstack/react-query";

import { fetchSession } from "./apiClient";

export const SESSION_QUERY_KEY = ["session"] as const;

export function useSession() {
  return useQuery({
    queryKey: SESSION_QUERY_KEY,
    queryFn: fetchSession,
    // A logged-out session is the ordinary case on first load, not an
    // error — don't retry it like a transient network failure.
    retry: false,
  });
}
