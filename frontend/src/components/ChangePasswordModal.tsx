import { type FormEvent, useState } from "react";

import { Button, TextInput } from "../design-system/components";
import { ModalFrame } from "./ModalFrame";
import { accountErrorMessage, changeOwnPassword, MIN_ADMIN_PASSWORD_LENGTH } from "../lib/api/admins";

export interface ChangePasswordModalProps {
  onDone: () => void;
  onCancel: () => void;
}

// The title bar's account-menu "Change Password" action (design handoff
// screen 3's "Notable Deviations" — a custom addition, not one of the 11
// numbered screens) — self-service only, per Stage 7's scope decision to
// leave other admins' credentials untouched by this slice.
export function ChangePasswordModal({ onDone, onCancel }: ChangePasswordModalProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("New password and confirmation don't match.");
      return;
    }
    if (newPassword.length < MIN_ADMIN_PASSWORD_LENGTH) {
      setError(`New password must be at least ${MIN_ADMIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setSubmitting(true);
    try {
      await changeOwnPassword(currentPassword, newPassword);
      onDone();
    } catch (err) {
      setError(accountErrorMessage(err, "Could not change password."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalFrame title="Change Password" onClose={onCancel} maxWidth={440}>
      <form onSubmit={submit}>
        {error && (
          <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 14 }}>
            {error}
          </div>
        )}
        <TextInput
          type="password"
          placeholder="Current password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          autoComplete="current-password"
          autoFocus
          style={{ width: "100%", marginBottom: 14 }}
          aria-label="Current password"
        />
        <TextInput
          type="password"
          placeholder={`New password (at least ${MIN_ADMIN_PASSWORD_LENGTH} characters)`}
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="new-password"
          style={{ width: "100%", marginBottom: 14 }}
          aria-label="New password"
        />
        <TextInput
          type="password"
          placeholder="Confirm new password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          autoComplete="new-password"
          style={{ width: "100%", marginBottom: 20 }}
          aria-label="Confirm new password"
        />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button type="button" variant="default" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" variant="accent" disabled={submitting}>
            Save
          </Button>
        </div>
      </form>
    </ModalFrame>
  );
}
