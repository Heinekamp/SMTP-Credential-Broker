import { Route, Routes } from "react-router-dom";

import { AuditLogList } from "./AuditLogList";

export function AuditLogRoutes() {
  return (
    <Routes>
      <Route index element={<AuditLogList />} />
    </Routes>
  );
}
