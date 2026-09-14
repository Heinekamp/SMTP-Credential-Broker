import { Route, Routes } from "react-router-dom";

import { TestConnection } from "./TestConnection";
import { UpstreamAccountForm } from "./UpstreamAccountForm";
import { UpstreamAccountsList } from "./UpstreamAccountsList";

export function UpstreamAccountsRoutes() {
  return (
    <Routes>
      <Route index element={<UpstreamAccountsList />} />
      <Route path="new" element={<UpstreamAccountForm />} />
      <Route path=":id/edit" element={<UpstreamAccountForm />} />
      <Route path=":id/test" element={<TestConnection />} />
    </Routes>
  );
}
