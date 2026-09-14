import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Button, Card, TextInput } from "../design-system/components";
import { ApiError, login, type RateLimitDetail } from "../lib/apiClient";
import { SESSION_QUERY_KEY } from "../lib/useSession";

type LoginStage = "normal" | "totp" | "rate-limited";

function formatRetryAfter(seconds: number): string {
  const minutes = Math.ceil(seconds / 60);
  return minutes <= 1 ? "1 minute" : `${minutes} minutes`;
}

export function Login() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [stage, setStage] = useState<LoginStage>("normal");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await login(email, password, stage === "totp" ? totpCode : undefined);
      if (response.totp_required) {
        setStage("totp");
        return;
      }
      // refetchQueries, not invalidateQueries: no route observes the
      // session query yet (we're still on /login), so invalidateQueries
      // would only mark the old cached value stale without replacing it
      // — RequireSession would then mount on "/" a moment later, read
      // that stale (pre-login, unauthenticated) value, and bounce straight
      // back to /login before the background refetch caught up. Real bug,
      // found via a real logout-then-log-back-in-with-TOTP run: the cache
      // must actually be correct *before* navigating, not just marked dirty.
      await queryClient.refetchQueries({ queryKey: SESSION_QUERY_KEY });
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const detail = err.detail as RateLimitDetail;
        setRetryMessage(`Too many attempts. Try again in ${formatRetryAfter(detail.retry_after_seconds)}.`);
        setStage("rate-limited");
      } else if (stage === "totp") {
        // Distinct from the email/password message on purpose: reaching
        // this step already proved the password was correct, so there's
        // nothing left to protect by staying generic here (backend/app/
        // api/routes/auth.py's login() returns this exact string).
        setError("Invalid authentication code.");
      } else {
        // Deliberately generic — never reveal whether the email or the
        // password was the wrong part (claude-design-prompt.md's Login spec).
        setError("Invalid email or password.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  const disabled = submitting || stage === "rate-limited";

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
      <Card style={{ width: "100%", maxWidth: 380, padding: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
          <img src="/logo.png" width={32} height={32} alt="" />
          <span style={{ fontSize: "var(--text-base)", fontWeight: 600 }}>SMTP Relay Console</span>
        </div>

        {stage === "rate-limited" && retryMessage && (
          <div
            style={{
              background: "var(--surface-well)",
              border: "1px solid var(--border-default)",
              borderLeft: "3px solid var(--warn)",
              borderRadius: "var(--radius-md)",
              padding: "12px 14px",
              marginBottom: 16,
              fontSize: "var(--text-sm)",
            }}
          >
            {retryMessage}
          </div>
        )}

        {error && (
          <div
            role="alert"
            style={{
              color: "var(--status-fault)",
              fontSize: "var(--text-sm)",
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={submit}>
          {stage === "totp" ? (
            <>
              <TextInput
                type="text"
                placeholder="000000"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                disabled={submitting}
                autoFocus
                style={{ width: "100%", marginBottom: 14 }}
                aria-label="Authentication code"
              />
              <Button type="submit" variant="accent" disabled={submitting} style={{ width: "100%", marginTop: 20 }}>
                Verify
              </Button>
              <button
                type="button"
                onClick={() => {
                  setStage("normal");
                  setTotpCode("");
                }}
                style={{
                  display: "block",
                  marginTop: 12,
                  background: "none",
                  border: "none",
                  color: "var(--text-muted)",
                  fontSize: "var(--text-2xs)",
                  cursor: "pointer",
                  padding: 0,
                }}
              >
                ← Back
              </button>
            </>
          ) : (
            <>
              <TextInput
                type="text"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={disabled}
                autoComplete="username"
                style={{ width: "100%", marginBottom: 14 }}
                aria-label="Email"
              />
              <TextInput
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={disabled}
                autoComplete="current-password"
                style={{ width: "100%", marginBottom: 14 }}
                aria-label="Password"
              />
              <Button
                type="submit"
                variant="accent"
                disabled={disabled}
                style={{ width: "100%", marginTop: 20 }}
              >
                Sign In
              </Button>
            </>
          )}
        </form>
      </Card>
    </div>
  );
}
