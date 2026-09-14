import type { MailStatus } from "../../lib/api/mailLog";
import type { StatusBadgeProps } from "../../design-system/components";

// Design handoff §8's fixed status color/shape mapping — never color-only,
// every badge pairs the dot with a text label.
export const MAIL_STATUS_BADGE: Record<MailStatus, { status: StatusBadgeProps["status"]; label: string }> = {
  sent: { status: "idle", label: "Sent" },
  queued: { status: "waiting", label: "Queued" },
  deferred: { status: "armed", label: "Deferred" },
  bounced: { status: "fault", label: "Bounced" },
  rejected: { status: "aborting", label: "Rejected" },
};
