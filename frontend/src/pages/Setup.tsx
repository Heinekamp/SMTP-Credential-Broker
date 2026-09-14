import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Button, Card, TextInput } from "../design-system/components";
import { submitSetup } from "../lib/api/setup";
import { SESSION_QUERY_KEY } from "../lib/useSession";

// Design handoff screen 2 — same centered-card shell as Login, first-run
// only. Hands off straight into the Dashboard's guided-empty state on
// submit (that's just the ordinary "nothing created yet" Dashboard render —
// see Dashboard.tsx — not a separate wizard flow).
export function Setup() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Password and confirmation don't match.");
      return;
    }
    setSubmitting(true);
    try {
      await submitSetup(email, password);
      // See Login.tsx's submit() for why this must be refetchQueries, not
      // invalidateQueries, before navigating.
      await queryClient.refetchQueries({ queryKey: SESSION_QUERY_KEY });
      navigate("/", { replace: true });
    } catch {
      setError("Could not create the admin account.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--surface-page)",
      }}
    >
      <Card style={{ width: "100%", maxWidth: 420, padding: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <img src="/logo.png" width={32} height={32} alt="" />
          <span style={{ fontSize: "var(--text-md)", fontWeight: 600 }}>Create the first admin account</span>
        </div>
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0, marginBottom: 20 }}>
          This account manages upstream mailboxes, senders, and local SMTP users for this relay.
        </p>

        {error && (
          <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 16 }}>
            {error}
          </div>
        )}

        <form onSubmit={submit}>
          <TextInput
            type="text"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
            autoComplete="username"
            style={{ width: "100%", marginBottom: 14 }}
            aria-label="Email"
          />
          <TextInput
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
            autoComplete="new-password"
            style={{ width: "100%", marginBottom: 14 }}
            aria-label="Password"
          />
          <TextInput
            type="password"
            placeholder="Confirm password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            disabled={submitting}
            autoComplete="new-password"
            style={{ width: "100%", marginBottom: 14 }}
            aria-label="Confirm password"
          />
          <Button type="submit" variant="accent" disabled={submitting} style={{ width: "100%", marginTop: 20 }}>
            Create Account
          </Button>
        </form>
      </Card>
    </div>
  );
}
