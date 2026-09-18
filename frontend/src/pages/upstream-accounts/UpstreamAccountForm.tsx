import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Select, TextInput } from "../../design-system/components";
import {
  createUpstreamAccount,
  getUpstreamAccount,
  updateUpstreamAccount,
  type TlsMode,
} from "../../lib/api/upstreamAccounts";

const QUERY_KEY = ["upstream-accounts"];

// Design handoff §5's Add/Edit form: Name, Host + Port (2:1 flex row), TLS
// Mode, Username, Password. The password field is write-only — never
// pre-filled on edit, not even with placeholder dots standing in for a
// real value.
export function UpstreamAccountForm() {
  const params = useParams<{ id: string }>();
  const isEdit = params.id !== undefined;
  const accountId = isEdit ? Number(params.id) : undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: existing } = useQuery({
    queryKey: [...QUERY_KEY, accountId],
    queryFn: () => getUpstreamAccount(accountId!),
    enabled: isEdit,
  });

  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [tlsMode, setTlsMode] = useState<TlsMode>("starttls");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rateLimitPerHour, setRateLimitPerHour] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Adjusts local state when the fetched entity changes, without an
  // Effect — https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevExisting, setPrevExisting] = useState(existing);
  if (existing !== prevExisting) {
    setPrevExisting(existing);
    if (existing) {
      setName(existing.name);
      setHost(existing.host);
      setPort(String(existing.port));
      setTlsMode(existing.tls_mode);
      setUsername(existing.username);
      setRateLimitPerHour(existing.rate_limit_per_hour === null ? "" : String(existing.rate_limit_per_hour));
    }
  }

  const save = useMutation({
    mutationFn: () => {
      const input = {
        name,
        host,
        port: Number(port),
        tls_mode: tlsMode,
        username,
        rate_limit_per_hour: rateLimitPerHour.trim() === "" ? null : Number(rateLimitPerHour),
        ...(password ? { password } : {}),
      };
      return isEdit ? updateUpstreamAccount(accountId!, input) : createUpstreamAccount({ ...input, password });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      navigate("/upstream-accounts");
    },
    onError: () => setError("Could not save this upstream account. Check the fields and try again."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate();
  }

  return (
    <Card style={{ maxWidth: 520 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0 }}>
        {isEdit ? "Edit Upstream Account" : "Add Upstream Account"}
      </h1>
      {error && (
        <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 14 }}>
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <label style={labelStyle} htmlFor="ua-name">Name</label>
        <TextInput id="ua-name" value={name} onChange={(e) => setName(e.target.value)} style={fieldStyle} required />

        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ flex: 2 }}>
            <label style={labelStyle} htmlFor="ua-host">Host</label>
            <TextInput id="ua-host" value={host} onChange={(e) => setHost(e.target.value)} style={fieldStyle} required />
          </div>
          <div style={{ flex: 1 }}>
            <label style={labelStyle} htmlFor="ua-port">Port</label>
            <TextInput
              id="ua-port"
              type="number"
              value={port}
              onChange={(e) => setPort(e.target.value)}
              style={fieldStyle}
              required
            />
          </div>
        </div>

        <label style={labelStyle} htmlFor="ua-tls-mode">TLS Mode</label>
        <Select
          id="ua-tls-mode"
          value={tlsMode}
          onChange={(e) => setTlsMode(e.target.value as TlsMode)}
          style={{ ...fieldStyle, width: "100%" }}
        >
          <option value="starttls">STARTTLS</option>
          <option value="implicit">Implicit TLS</option>
        </Select>

        <label style={labelStyle} htmlFor="ua-username">Username</label>
        <TextInput id="ua-username" value={username} onChange={(e) => setUsername(e.target.value)} style={fieldStyle} required />

        <label style={labelStyle} htmlFor="ua-password">Password</label>
        <TextInput
          id="ua-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={fieldStyle}
          required={!isEdit}
        />
        {isEdit && (
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -8, marginBottom: 14 }}>
            This field is write-only and never shows the stored password. Leave blank to keep the current password.
          </p>
        )}

        <label style={labelStyle} htmlFor="ua-rate-limit">Rate Limit (messages/hour)</label>
        <TextInput
          id="ua-rate-limit"
          type="number"
          min={1}
          placeholder="Unlimited"
          value={rateLimitPerHour}
          onChange={(e) => setRateLimitPerHour(e.target.value)}
          style={fieldStyle}
        />
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -8, marginBottom: 14 }}>
          Blank means unlimited. Paces outbound delivery to this provider rather than rejecting anything — excess
          mail sits in the queue and goes out once the pace allows it, protecting this mailbox's reputation.
          {isEdit && existing && ` Sent in the last hour: ${existing.sent_this_hour}.`}
        </p>

        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <Button type="submit" variant="accent" disabled={save.isPending}>
            Save
          </Button>
          <Button type="button" variant="default" onClick={() => navigate("/upstream-accounts")}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

const labelStyle = {
  display: "block",
  fontSize: "var(--text-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase" as const,
  letterSpacing: "var(--tracking-label)",
  marginBottom: 4,
};

const fieldStyle = { width: "100%", marginBottom: 14 };
