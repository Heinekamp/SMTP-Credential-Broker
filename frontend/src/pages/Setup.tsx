import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { BrandLogo } from "../components/BrandLogo";
import { Button, Card, TextInput } from "../design-system/components";
import { MIN_ADMIN_PASSWORD_LENGTH } from "../lib/api/admins";
import { submitSetup } from "../lib/api/setup";
import { confirmSessionEstablished, sessionCookieRejectedMessage } from "../lib/useSession";

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
    if (password.length < MIN_ADMIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_ADMIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setSubmitting(true);
    try {
      await submitSetup(email, password);
    } catch {
      setError("Could not create the admin account.");
      setSubmitting(false);
      return;
    }
    try {
      // See Login.tsx's submit() for why the session must be fetched, not
      // just invalidated, before navigating.
      if (!(await confirmSessionEstablished(queryClient))) {
        // The account exists now; only the cookie is missing (#212).
        setError(`Admin account created, but you aren't logged in. ${sessionCookieRejectedMessage()}`);
        return;
      }
      navigate("/", { replace: true });
    } catch {
      setError("Admin account created, but the session couldn't be checked. Reload the page to log in.");
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
          <BrandLogo width={32} height={32} />
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
            placeholder={`Password (at least ${MIN_ADMIN_PASSWORD_LENGTH} characters)`}
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
