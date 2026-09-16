import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Switch, TextInput } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { ConfirmModal } from "../../components/ConfirmModal";
import { ApiError } from "../../lib/apiClient";
import { relativeTime } from "../../lib/relativeTime";
import {
  deleteLocalUser,
  deleteLocalUserPrecheck,
  listLocalUsers,
  regenerateLocalUserPassword,
  updateLocalUser,
  type LocalUser,
} from "../../lib/api/localUsers";

const QUERY_KEY = ["local-users"];

// A single numeric field bound to one of LocalUser's rate-limit values,
// editable in place like the enabled Switch column next to it — there's
// no separate edit page for local users, only Add.
function InlineNumberField({
  currentValue,
  placeholder,
  disabled,
  saving,
  onSave,
}: {
  currentValue: number | null;
  placeholder: string;
  disabled?: boolean;
  saving: boolean;
  onSave: (value: number | null) => void;
}) {
  const [value, setValue] = useState(currentValue === null ? "" : String(currentValue));

  useEffect(() => {
    setValue(currentValue === null ? "" : String(currentValue));
  }, [currentValue]);

  function commit() {
    const trimmed = value.trim();
    const parsed = trimmed === "" ? null : Number(trimmed);
    if (parsed === currentValue) return;
    if (parsed !== null && (!Number.isInteger(parsed) || parsed < 1)) {
      setValue(currentValue === null ? "" : String(currentValue));
      return;
    }
    onSave(parsed);
  }

  return (
    <TextInput
      type="number"
      min={1}
      placeholder={placeholder}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      disabled={disabled || saving}
      style={{ width: 90 }}
    />
  );
}

function RateLimitCell({
  user,
  onSaveHourly,
  onSaveBurst,
  savingHourly,
  savingBurst,
}: {
  user: LocalUser;
  onSaveHourly: (value: number | null) => void;
  onSaveBurst: (value: number | null) => void;
  savingHourly: boolean;
  savingBurst: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div>
        <InlineNumberField
          currentValue={user.rate_limit_per_hour}
          placeholder="Unlimited"
          saving={savingHourly}
          onSave={onSaveHourly}
        />
        {user.rate_limit_per_hour !== null && (
          <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>
            {user.sent_this_hour}/{user.rate_limit_per_hour} this hour
          </div>
        )}
      </div>
      <div>
        <InlineNumberField
          currentValue={user.rate_limit_burst}
          placeholder="No burst limit"
          disabled={user.rate_limit_per_hour === null}
          saving={savingBurst}
          onSave={onSaveBurst}
        />
        {user.rate_limit_burst !== null && (
          <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>
            {user.burst_tokens_available}/{user.rate_limit_burst} available
          </div>
        )}
      </div>
    </div>
  );
}

export function LocalUsersList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: users, isLoading, isError } = useQuery({ queryKey: QUERY_KEY, queryFn: listLocalUsers });

  const [disableTarget, setDisableTarget] = useState<LocalUser | null>(null);
  const [disableError, setDisableError] = useState<string | null>(null);
  const [regenerateTarget, setRegenerateTarget] = useState<LocalUser | null>(null);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LocalUser | null>(null);
  const [deletePrecheck, setDeletePrecheck] = useState<string[] | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function errorMessage(err: unknown, fallback: string): string {
    return err instanceof ApiError && typeof err.detail === "string" ? err.detail : fallback;
  }

  const toggleEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateLocalUser(id, { enabled }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      // Re-enabling issues a fresh credential (no plaintext to restore) —
      // the response carries it once, same as create/regenerate.
      if (result.password) {
        navigate(`/local-users/${result.user.id}/reveal`, { state: { password: result.password } });
      }
    },
    onError: (err) => setDisableError(errorMessage(err, "Could not change this user's status.")),
  });

  const updateRateLimit = useMutation({
    mutationFn: ({ id, rate_limit_per_hour }: { id: number; rate_limit_per_hour: number | null }) => {
      // Clearing the hourly limit clears any burst limit too — a burst
      // value has no effect without one, and the API rejects the
      // combination outright.
      const input = rate_limit_per_hour === null ? { rate_limit_per_hour, rate_limit_burst: null } : { rate_limit_per_hour };
      return updateLocalUser(id, input);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const updateRateLimitBurst = useMutation({
    mutationFn: ({ id, rate_limit_burst }: { id: number; rate_limit_burst: number | null }) =>
      updateLocalUser(id, { rate_limit_burst }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const regenerate = useMutation({
    mutationFn: (id: number) => regenerateLocalUserPassword(id),
    onSuccess: (result, id) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setRegenerateTarget(null);
      navigate(`/local-users/${id}/reveal`, { state: { password: result.password } });
    },
    onError: (err) => setRegenerateError(errorMessage(err, "Could not regenerate this user's password.")),
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteLocalUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDeleteTarget(null);
      setDeletePrecheck(null);
      setDeleteError(null);
    },
    onError: (err) => setDeleteError(errorMessage(err, "Could not delete this user.")),
  });

  async function openDeleteModal(user: LocalUser) {
    const precheck = await deleteLocalUserPrecheck(user.id);
    setDeleteTarget(user);
    setDeletePrecheck(precheck.allowed_sender_addresses);
    setDeleteError(null);
  }

  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, margin: 0 }}>Local SMTP Users</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <a href="/api/exports/local-users.csv" style={exportLinkStyle}>
            Export CSV
          </a>
          <Button variant="accent" onClick={() => navigate("/local-users/new")}>
            + Add Local SMTP User
          </Button>
        </div>
      </div>

      {isLoading && (
        <Card>
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
        </Card>
      )}

      {isError && (
        <Card style={{ borderLeft: "3px solid var(--status-fault)" }}>
          <p style={{ margin: 0, fontWeight: 600 }}>Couldn't load local SMTP users.</p>
          <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
            This is a connectivity/API issue, not a sign that there's no data.
          </p>
        </Card>
      )}

      {users && users.length === 0 && (
        <Card style={{ maxWidth: 480, textAlign: "center" }}>
          <p style={{ color: "var(--text-muted)" }}>
            No local SMTP users yet. Issue scoped credentials for internal services here.
          </p>
          <Button variant="accent" onClick={() => navigate("/local-users/new")}>
            + Add Local SMTP User
          </Button>
        </Card>
      )}

      {users && users.length > 0 && (
        <table style={tableStyle}>
          <thead>
            <tr>
              {["Name", "Username", "Status", "Password Changed", "Allowed Senders", "Rate Limit", "Actions"].map((label) => (
                <th key={label} style={thStyle}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td style={{ ...tdStyle, fontWeight: 600 }}>{user.name}</td>
                <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                  {user.username}
                </td>
                <td style={tdStyle}>
                  <Switch
                    checked={user.enabled}
                    onChange={(checked) => {
                      setDisableError(null);
                      if (checked) {
                        toggleEnabled.mutate({ id: user.id, enabled: true });
                      } else {
                        setDisableTarget(user);
                      }
                    }}
                  />
                </td>
                <td style={{ ...tdStyle, color: "var(--text-muted)" }}>
                  {user.password_last_rotated_at ? relativeTime(user.password_last_rotated_at) : "—"}
                </td>
                <td style={tdStyle}>
                  <button
                    type="button"
                    onClick={() => navigate(`/local-users/${user.id}/permissions`)}
                    style={linkButtonStyle}
                  >
                    {user.allowed_sender_count} allowed
                  </button>
                </td>
                <td style={tdStyle}>
                  <RateLimitCell
                    user={user}
                    savingHourly={updateRateLimit.isPending}
                    savingBurst={updateRateLimitBurst.isPending}
                    onSaveHourly={(rate_limit_per_hour) => updateRateLimit.mutate({ id: user.id, rate_limit_per_hour })}
                    onSaveBurst={(rate_limit_burst) => updateRateLimitBurst.mutate({ id: user.id, rate_limit_burst })}
                  />
                </td>
                <td style={tdStyle}>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <Button variant="default" onClick={() => navigate(`/local-users/${user.id}/permissions`)}>
                      Permissions
                    </Button>
                    <Button variant="default" onClick={() => navigate(`/local-users/${user.id}/connection-details`)}>
                      Connection Details
                    </Button>
                    <Button
                      variant="warn"
                      onClick={() => {
                        setRegenerateTarget(user);
                        setRegenerateError(null);
                      }}
                    >
                      Regenerate
                    </Button>
                    <Button variant="danger" onClick={() => openDeleteModal(user)}>
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {disableTarget && (
        <ConfirmModal
          title={`Disable "${disableTarget.name}"?`}
          body="This credential will stop authenticating immediately until it is re-enabled."
          confirmLabel="Disable"
          variant="danger"
          confirming={toggleEnabled.isPending}
          error={disableError}
          onCancel={() => {
            setDisableTarget(null);
            setDisableError(null);
          }}
          onConfirm={() => {
            toggleEnabled.mutate({ id: disableTarget.id, enabled: false }, { onSuccess: () => setDisableTarget(null) });
          }}
        />
      )}

      {regenerateTarget && (
        <ConfirmModal
          title={`Regenerate password for "${regenerateTarget.name}"?`}
          body="This invalidates the current credential immediately. The service using it will be unable to send until it is reconfigured with the new password."
          confirmLabel="Regenerate"
          variant="warn"
          confirming={regenerate.isPending}
          error={regenerateError}
          onCancel={() => {
            setRegenerateTarget(null);
            setRegenerateError(null);
          }}
          onConfirm={() => regenerate.mutate(regenerateTarget.id)}
        />
      )}

      {deleteTarget && deletePrecheck && (
        <ConfirmModal
          title={`Delete "${deleteTarget.name}"?`}
          body={
            deletePrecheck.length === 0
              ? "This credential will stop authenticating immediately. It wasn't allowed to use any senders."
              : `This credential will stop authenticating immediately. It was allowed to use: ${deletePrecheck.join(", ")}`
          }
          confirmLabel="Delete"
          variant="danger"
          confirming={remove.isPending}
          error={deleteError}
          onCancel={() => {
            setDeleteTarget(null);
            setDeletePrecheck(null);
            setDeleteError(null);
          }}
          onConfirm={() => remove.mutate(deleteTarget.id)}
        />
      )}
    </div>
  );
}

const linkButtonStyle = {
  background: "none",
  border: "none",
  padding: 0,
  color: "var(--brand-green)",
  cursor: "pointer",
  fontSize: "var(--text-sm)",
  fontFamily: "var(--font-ui)",
  textDecoration: "underline",
};

// Same visual weight as Button's "default" variant — a plain <a> (not
// Button, which only ever renders a <button>) so the browser handles the
// download via the response's Content-Disposition header, cookies and
// all, with no JS involved.
const exportLinkStyle = {
  padding: "8px 14px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-default)",
  background: "var(--surface-control)",
  color: "var(--text-body)",
  cursor: "pointer",
  fontSize: "var(--text-sm)",
  fontFamily: "var(--font-ui)",
  textDecoration: "none",
  display: "inline-flex",
  alignItems: "center",
};
