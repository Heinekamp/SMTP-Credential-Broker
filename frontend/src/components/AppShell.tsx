import { Outlet } from "react-router-dom";

import { Sidenav } from "./Sidenav";
import { Titlebar } from "./Titlebar";

// Design handoff §3: a CSS grid — 56px title row + fluid content row,
// (auto/200px, collapsing to 56px below 900px via Sidenav's own media
// query) sidenav column + 1fr content column. The content area scrolls
// both axes independently of the shell so wide tables never break the
// page layout at tablet width.
export function AppShell() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "56px 1fr",
        gridTemplateColumns: "auto 1fr",
        height: "100vh",
        background: "var(--surface-page)",
      }}
    >
      <div style={{ gridColumn: "1 / -1" }}>
        <Titlebar />
      </div>
      <Sidenav />
      <main style={{ overflow: "auto", padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
