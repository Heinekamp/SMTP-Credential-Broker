import { Route, Routes } from "react-router-dom";

import { SenderForm } from "./SenderForm";
import { SenderPermissions } from "./SenderPermissions";
import { SendersList } from "./SendersList";

export function SendersRoutes() {
  return (
    <Routes>
      <Route index element={<SendersList />} />
      <Route path="new" element={<SenderForm />} />
      <Route path=":id/edit" element={<SenderForm />} />
      <Route path=":id/permissions" element={<SenderPermissions />} />
    </Routes>
  );
}
