import { Route, Routes } from "react-router-dom";

import { ConnectionDetailsView } from "./ConnectionDetailsView";
import { LocalUserAddForm } from "./LocalUserAddForm";
import { LocalUserPermissions } from "./LocalUserPermissions";
import { LocalUsersList } from "./LocalUsersList";
import { PasswordReveal } from "./PasswordReveal";

export function LocalUsersRoutes() {
  return (
    <Routes>
      <Route index element={<LocalUsersList />} />
      <Route path="new" element={<LocalUserAddForm />} />
      <Route path=":id/reveal" element={<PasswordReveal />} />
      <Route path=":id/permissions" element={<LocalUserPermissions />} />
      <Route path=":id/connection-details" element={<ConnectionDetailsView />} />
    </Routes>
  );
}
