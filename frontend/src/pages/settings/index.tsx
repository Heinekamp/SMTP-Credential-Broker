import { useState } from "react";

import { Tabs } from "../../design-system/components";
import { AdminsTab } from "./AdminsTab";
import { SystemTab } from "./SystemTab";

// Design handoff §10.
export function Settings() {
  const [tab, setTab] = useState<"admins" | "system">("admins");

  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginBottom: 12 }}>Settings</h1>
      <div style={{ marginBottom: 16 }}>
        <Tabs
          tabs={[
            { value: "admins", label: "Admins" },
            { value: "system", label: "System" },
          ]}
          active={tab}
          onChange={(value) => setTab(value as "admins" | "system")}
        />
      </div>
      {tab === "admins" ? <AdminsTab /> : <SystemTab />}
    </div>
  );
}
