import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Button, Card } from "../design-system/components";
import { logout } from "../lib/apiClient";
import { SESSION_QUERY_KEY, useSession } from "../lib/useSession";

// Proves the session/CSRF/logout plumbing works end to end. The real
// authenticated app shell (Titlebar/Sidenav/Dashboard) is Stage 7 — see
// docs/implementation-plan.md.
export function AuthenticatedPlaceholder() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: session } = useSession();

  async function handleLogout() {
    await logout();
    await queryClient.invalidateQueries({ queryKey: SESSION_QUERY_KEY });
    navigate("/login", { replace: true });
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--surface-page)",
      }}
    >
      <Card style={{ width: "100%", maxWidth: 420, padding: 32 }}>
        <p style={{ marginTop: 0 }}>
          Logged in as <strong>{session?.email}</strong>.
        </p>
        <Button variant="default" onClick={handleLogout}>
          Log Out
        </Button>
      </Card>
    </div>
  );
}
