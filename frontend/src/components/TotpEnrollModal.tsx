import { type FormEvent, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

import { Button, TextInput } from "../design-system/components";
import { ModalFrame } from "./ModalFrame";
import { accountErrorMessage, confirmTotp, enrollTotp } from "../lib/api/admins";

export interface TotpEnrollModalProps {
  onDone: () => void;
  onCancel: () => void;
}

// TOTP enrollment (Stage 8) — no design-handoff screen covers this in
// detail (it was out of scope until now), so this reuses the same
// ModalFrame as ChangePasswordModal.tsx and the same
// monospace-box pattern as the one-time password reveal
// (local-users/PasswordReveal.tsx) for the secret. A QR code (added later,
// see issue #2) sits alongside the copyable text rather than replacing it
// — most authenticator apps are on a phone and scan a code, but the raw
// secret stays available for manual entry.
export function TotpEnrollModal({ onDone, onCancel }: TotpEnrollModalProps) {
  const [secret, setSecret] = useState<string | null>(null);
  const [otpauthUri, setOtpauthUri] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    enrollTotp()
      .then((result) => {
        setSecret(result.secret);
        setOtpauthUri(result.otpauth_uri);
      })
      // Without this, any failure left "Generating secret…" on screen forever (#207).
      .catch((err) => setError(accountErrorMessage(err, "Could not start TOTP enrollment.")));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!secret) return;
    setError(null);
    setSubmitting(true);
    try {
      await confirmTotp(secret, code, currentPassword);
      onDone();
    } catch (err) {
      setError(accountErrorMessage(err, "Could not enable TOTP."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame title="Enroll TOTP" onClose={onCancel} maxWidth={480}>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0, marginBottom: 16 }}>
        Add this secret to your authenticator app, then enter a code to confirm.
      </p>

      {secret && otpauthUri ? (
        <form onSubmit={submit}>
          {error && (
            <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 14 }}>
              {error}
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}>
            <div style={{ background: "#fff", padding: 12, borderRadius: "var(--radius-sm)" }}>
              <QRCodeSVG value={otpauthUri} size={176} />
            </div>
          </div>

          <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "var(--tracking-label)", marginBottom: 4 }}>
            Secret
          </div>
          <div
            style={{
              background: "var(--surface-well)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-sm)",
              padding: "10px 12px",
              marginBottom: 12,
              fontFamily: "var(--font-mono)",
              fontSize: "var(--text-sm)",
              wordBreak: "break-all",
            }}
          >
            {secret}
          </div>

          <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "var(--tracking-label)", marginBottom: 4 }}>
            Setup URI
          </div>
          <div
            style={{
              background: "var(--surface-well)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--radius-sm)",
              padding: "10px 12px",
              marginBottom: 16,
              fontFamily: "var(--font-mono)",
              fontSize: "var(--text-2xs)",
              color: "var(--text-muted)",
              wordBreak: "break-all",
            }}
          >
            {otpauthUri}
          </div>

          <TextInput
            type="text"
            placeholder="000000"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoFocus
            style={{ width: "100%", marginBottom: 12 }}
            aria-label="Authentication code"
          />
          <TextInput
            type="password"
            placeholder="Current password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
            style={{ width: "100%", marginBottom: 16 }}
            aria-label="Current password"
          />

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button type="button" variant="default" onClick={onCancel} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" variant="accent" disabled={submitting || !code || !currentPassword}>
              Verify &amp; Enable
            </Button>
          </div>
        </form>
      ) : (
        <>
          {error ? (
            <p role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)" }}>
              {error}
            </p>
          ) : (
            <p style={{ color: "var(--text-muted)" }}>Generating secret…</p>
          )}
          <Button type="button" variant="default" onClick={onCancel}>
            Close
          </Button>
        </>
      )}
    </ModalFrame>
  );
}
