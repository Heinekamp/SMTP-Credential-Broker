import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "./components/AppShell";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
import { AuditLogRoutes } from "./pages/audit-log";
import { LocalUsersRoutes } from "./pages/local-users";
import { MailLogRoutes } from "./pages/mail-log";
import { Queue } from "./pages/Queue";
import { SendersRoutes } from "./pages/senders";
import { Settings } from "./pages/settings";
import { UpstreamAccountsRoutes } from "./pages/upstream-accounts";
import { fetchSetupRequired } from "./lib/api/setup";
import { useSession } from "./lib/useSession";

function RequireSession({ children }: { children: ReactNode }) {
  const { data, isLoading } = useSession();
  if (isLoading) return null;
  if (!data?.authenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** /login redirects to /setup on a genuinely fresh install (no admin
 * exists yet) instead of showing a login form with nothing to log into. */
function LoginOrSetupRedirect() {
  const { data, isLoading } = useQuery({ queryKey: ["setup-required"], queryFn: fetchSetupRequired });
  if (isLoading) return null;
  if (data?.setup_required) return <Navigate to="/setup" replace />;
  return <Login />;
}

/** /setup redirects to /login once setup has already been completed —
 * this must never become a lingering second way to create an admin. */
function SetupOrLoginRedirect() {
  const { data, isLoading } = useQuery({ queryKey: ["setup-required"], queryFn: fetchSetupRequired });
  if (isLoading) return null;
  if (data?.setup_required === false) return <Navigate to="/login" replace />;
  return <Setup />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginOrSetupRedirect />} />
      <Route path="/setup" element={<SetupOrLoginRedirect />} />
      <Route
        element={
          <RequireSession>
            <AppShell />
          </RequireSession>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/upstream-accounts/*" element={<UpstreamAccountsRoutes />} />
        <Route path="/senders/*" element={<SendersRoutes />} />
        <Route path="/local-users/*" element={<LocalUsersRoutes />} />
        <Route path="/mail-log/*" element={<MailLogRoutes />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/audit-log/*" element={<AuditLogRoutes />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
