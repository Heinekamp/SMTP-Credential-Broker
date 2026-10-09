import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { App } from "./App";
import { BrandingEffects } from "./components/BrandingEffects";
import { ThemeProvider } from "./components/ThemeProvider";
import "./design-system/tokens/index.css";

// Any successful change may have put the database out of sync with the
// configuration Postfix is running — refresh the health check right away so
// the pending-changes banner (PendingConfigBanner.tsx, #177) reflects it
// without waiting for the next 30s poll.
const queryClient: QueryClient = new QueryClient({
  mutationCache: new MutationCache({
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["health"] }),
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
