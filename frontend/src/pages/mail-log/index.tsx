import { Route, Routes } from "react-router-dom";

import { MailLogDetail } from "./MailLogDetail";
import { MailLogList } from "./MailLogList";

export function MailLogRoutes() {
  return (
    <Routes>
      <Route index element={<MailLogList />} />
      <Route path=":id" element={<MailLogDetail />} />
    </Routes>
  );
}
