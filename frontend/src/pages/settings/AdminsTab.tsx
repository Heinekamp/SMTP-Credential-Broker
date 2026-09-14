import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, StatusBadge, TextInput } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { ChangePasswordModal } from "../../components/ChangePasswordModal";
import { ApiError } from "../../lib/apiClient";
import { createAdmin, listAdmins } from "../../lib/api/admins";
import { useSession } from "../../lib/useSession";

const QUERY_KEY = ["admins"];

// Design handoff §10's Admins tab. TOTP Enroll/Remove and resetting
// another admin's password are deliberately disabled controls here --
// implementation-plan.md assigns full TOTP support to Stage 8, and no
// admin-reset-someone-else's-password endpoint exists (only self-service
// change, which needs the current password) -- rather than pulling that
// scope forward, per the project's own Stage 7/8 sequencing decision.
export function AdminsTab() {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const { data: admins, isLoading } = useQuery({ queryKey: QUERY_KEY, queryFn: listAdmins });

  const [showAddForm, setShowAddForm] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [changingOwnPassword, setChangingOwnPassword] = useState(false);

  const create = useMutation({
    mutationFn: () => createAdmin(email, password),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setShowAddForm(false);
      setEmail("");
      setPassword("");
    },
    onError: (err) => {
      setError(err instanceof ApiError && err.status === 409 ? "An admin with this email already exists." : "Could not create this admin.");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <Button variant="accent" onClick={() => setShowAddForm((v) => !v)}>
          + Add Admin
        </Button>
      </div>

      {showAddForm && (
        <Card style={{ maxWidth: 420, marginBottom: 16 }}>
          <form onSubmit={submit}>
            {error && (
              <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 14 }}>
                {error}
              </div>
            )}
            <TextInput
              type="text"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ width: "100%", marginBottom: 14 }}
              aria-label="New admin email"
            />
            <TextInput
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ width: "100%", marginBottom: 14 }}
              aria-label="New admin password"
            />
            <div style={{ display: "flex", gap: 8 }}>
              <Button type="submit" variant="accent" disabled={create.isPending}>
                Create
              </Button>
              <Button type="button" variant="default" onClick={() => setShowAddForm(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {isLoading && (
        <Card>
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
        </Card>
      )}

      {admins && (
        <table style={tableStyle}>
          <thead>
            <tr>
              {["Email", "TOTP", "Actions"].map((label) => (
                <th key={label} style={thStyle}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {admins.map((admin) => (
              <tr key={admin.id}>
                <td style={tdStyle}>{admin.email}</td>
                <td style={tdStyle}>
                  <StatusBadge
                    status={admin.totp_enabled ? "idle" : "waiting"}
                    label={admin.totp_enabled ? "Enabled" : "Disabled"}
                    size="sm"
                  />
                </td>
                <td style={tdStyle}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                    <Button variant="default" disabled title="Lands in the Stage 8 hardening pass">
                      {admin.totp_enabled ? "Remove TOTP" : "Enroll TOTP"}
                    </Button>
                    {admin.email === session?.email && (
                      <Button variant="default" onClick={() => setChangingOwnPassword(true)}>
                        Change Password
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
        TOTP enrollment lands in the Stage 8 hardening pass.
      </p>

      {changingOwnPassword && (
        <ChangePasswordModal onDone={() => setChangingOwnPassword(false)} onCancel={() => setChangingOwnPassword(false)} />
      )}
    </div>
  );
}
