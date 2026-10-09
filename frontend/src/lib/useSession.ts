import { type QueryClient, useQuery } from "@tanstack/react-query";

import { fetchSession, type SessionInfo } from "./apiClient";

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

/** Fetches the session after a successful login/setup, storing it in the
 * cache, and reports whether it actually took. The cache must be correct
 * *before* navigating — see Login.tsx's submit(). fetchQuery, not
 * refetchQueries: on /login the session query may not exist in the cache
 * yet, and refetchQueries then fetches nothing at all. */
export async function confirmSessionEstablished(queryClient: QueryClient): Promise<boolean> {
  const session = await queryClient.fetchQuery<SessionInfo>({
    queryKey: SESSION_QUERY_KEY,
    queryFn: fetchSession,
    staleTime: 0,
  });
  return session.authenticated;
}

/** The server accepted the credentials but the browser didn't keep the
 * session cookie — almost always a Secure cookie on a plain-HTTP page,
 * which used to just bounce back to the login form with no explanation
 * (#212). */
export function sessionCookieRejectedMessage(): string {
  if (window.location.protocol === "http:") {
    return (
      "Your browser didn't keep the session cookie: the relay sends HTTPS-only cookies, but this page is " +
      "plain HTTP. Open it over HTTPS, or set RELAY_COOKIE_SECURE=false in .env and restart the app " +
      "(docker compose up -d) — see docs/installation.md."
    );
  }
  return "Your browser didn't keep the session cookie. Allow cookies for this site and try again.";
}
