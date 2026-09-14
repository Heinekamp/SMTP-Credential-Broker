import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AuthenticatedPlaceholder } from "./pages/AuthenticatedPlaceholder";
import { Login } from "./pages/Login";
import { useSession } from "./lib/useSession";

function RequireSession({ children }: { children: ReactNode }) {
  const { data, isLoading } = useSession();
  if (isLoading) return null;
  if (!data?.authenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireSession>
            <AuthenticatedPlaceholder />
          </RequireSession>
        }
      />
    </Routes>
  );
}
