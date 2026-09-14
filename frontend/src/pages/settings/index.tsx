import { useState } from "react";

import { Tabs } from "../../design-system/components";
import { AdminsTab } from "./AdminsTab";
import { NotificationsTab } from "./NotificationsTab";
import { SystemTab } from "./SystemTab";

type SettingsTab = "admins" | "system" | "notifications";

// Design handoff §10.
export function Settings() {
  const [tab, setTab] = useState<SettingsTab>("admins");

  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginBottom: 12 }}>Settings</h1>
      <div style={{ marginBottom: 16 }}>
        <Tabs
          tabs={[
            { value: "admins", label: "Admins" },
            { value: "system", label: "System" },
            { value: "notifications", label: "Notifications" },
          ]}
          active={tab}
          onChange={(value) => setTab(value as SettingsTab)}
        />
      </div>
      {tab === "admins" && <AdminsTab />}
      {tab === "system" && <SystemTab />}
      {tab === "notifications" && <NotificationsTab />}
    </div>
  );
}
