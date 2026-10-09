import type { ReactNode } from "react";

import { Button } from "../design-system/components";
import { ModalFrame } from "./ModalFrame";

export interface ConfirmModalProps {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  /** danger = delete/disable/remove-TOTP. warn = regenerate/rotate-key. */
  variant?: "danger" | "warn";
  onConfirm: () => void;
  onCancel: () => void;
  confirming?: boolean;
  /** A mutation failure (e.g. a 409 conflict) — rendered as an inline
   * alert instead of letting it fail silently. */
  error?: string | null;
  /** True when confirming is known in advance to be pointless (e.g. a
   * delete-precheck already showed this can't succeed) — disables the
   * confirm button rather than letting the admin trigger a doomed
   * request, with `body` expected to explain why. */
  confirmDisabled?: boolean;
}

// Design handoff screen 11's shared confirmation-modal pattern: a
// full-screen scrim (the design's one documented use of transparency),
// a centered card, a bold title, plain-language concrete consequence
// text (never a generic "are you sure?"), Cancel + a colored Confirm.
export function ConfirmModal({
  title,
  body,
  confirmLabel,
  variant = "danger",
  onConfirm,
  onCancel,
  confirming = false,
  error = null,
  confirmDisabled = false,
}: ConfirmModalProps) {
  return (
    <ModalFrame title={title} onClose={onCancel}>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)", marginBottom: 20, lineHeight: "var(--leading-normal)" }}>
        {body}
      </div>
      {error && (
        <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 16 }}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <Button variant="default" onClick={onCancel} disabled={confirming}>
          Cancel
        </Button>
        <Button
          variant={variant}
          onClick={onConfirm}
          disabled={confirming || confirmDisabled}
          title={confirmDisabled ? "See above — this can't be deleted right now" : undefined}
        >
          {confirmLabel}
        </Button>
      </div>
    </ModalFrame>
  );
}
