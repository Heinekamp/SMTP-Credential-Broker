import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "./components/AppShell";
import { ComingSoon } from "./pages/ComingSoon";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
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
        <Route path="/" element={<ComingSoon title="Dashboard" />} />
        <Route path="/upstream-accounts/*" element={<ComingSoon title="Upstream Accounts" />} />
        <Route path="/senders/*" element={<ComingSoon title="Senders" />} />
        <Route path="/local-users/*" element={<ComingSoon title="Local SMTP Users" />} />
        <Route path="/mail-log" element={<ComingSoon title="Mail Log" />} />
        <Route path="/queue" element={<ComingSoon title="Queue" />} />
        <Route path="/settings" element={<ComingSoon title="Settings" />} />
      </Route>
    </Routes>
  );
}
