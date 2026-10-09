import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { App } from "./App";
import { BrandingEffects } from "./components/BrandingEffects";
import { ThemeProvider } from "./components/ThemeProvider";
import { ApiError } from "./lib/apiClient";
import { SESSION_QUERY_KEY } from "./lib/useSession";
import "./design-system/tokens/index.css";

// Any successful change may have put the database out of sync with the
// configuration Postfix is running — refresh the health check right away so
// the pending-changes banner (PendingConfigBanner.tsx, #177) reflects it
// without waiting for the next 30s poll.
// A 401 from anything may mean the session expired — re-check it, so an
// expired session lands on /login instead of every page showing "couldn't
// load" (#207). Re-checking rather than assuming: some endpoints also use
// 401 for "current password is incorrect", which must not log anyone out.
function recheckSessionOn401(err: unknown) {
  if (err instanceof ApiError && err.status === 401) {
    queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: recheckSessionOn401 }),
  mutationCache: new MutationCache({
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["health"] }),
    onError: recheckSessionOn401,
  }),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrandingEffects />
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
