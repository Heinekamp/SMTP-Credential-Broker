import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, StatusBadge } from "../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../design-system/table";
import { ConfirmModal } from "../components/ConfirmModal";
import { ApiError } from "../lib/apiClient";
import { relativeTime } from "../lib/relativeTime";
import { deleteQueueMessage, listQueue, retryQueueMessage, type QueueEntry } from "../lib/api/queue";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError && typeof err.detail === "string" ? err.detail : fallback;
}

const QUERY_KEY = ["queue"];

function statusFor(queueName: string): { status: "running" | "armed"; label: string } {
  if (queueName === "active") return { status: "running", label: "Active" };
  return { status: "armed", label: queueName.charAt(0).toUpperCase() + queueName.slice(1) || "Deferred" };
}

// Design handoff §9. Retry is immediate (low-risk, no confirmation);
// Delete opens a confirmation modal naming the permanent, no-retry
// consequence.
export function Queue() {
  const queryClient = useQueryClient();
  const { data: entries, isLoading, isError } = useQuery({ queryKey: QUERY_KEY, queryFn: listQueue });
  const [deleteTarget, setDeleteTarget] = useState<QueueEntry | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [retryError, setRetryError] = useState<string | null>(null);

  const retry = useMutation({
    mutationFn: (queueId: string) => retryQueueMessage(queueId),
    onMutate: () => setRetryError(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
    onError: (err) => setRetryError(errorMessage(err, "Could not retry this message.")),
  });

  const remove = useMutation({
    mutationFn: (queueId: string) => deleteQueueMessage(queueId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDeleteTarget(null);
      setDeleteError(null);
    },
    onError: (err) => setDeleteError(errorMessage(err, "Could not delete this message.")),
  });

  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginBottom: 12 }}>Queue</h1>

      {isLoading && (
        <Card>
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
          <div style={skeletonBarStyle} />
        </Card>
      )}

      {isError && (
        <Card style={{ borderLeft: "3px solid var(--status-fault)" }}>
          <p style={{ margin: 0, fontWeight: 600 }}>Couldn't load the queue.</p>
          <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
            This is a connectivity/API issue, not a sign that there's nothing queued.
          </p>
        </Card>
      )}

      {retryError && (
        <Card style={{ borderLeft: "3px solid var(--status-fault)", marginBottom: 12 }}>
          <p role="alert" style={{ margin: 0, color: "var(--status-fault)" }}>
            {retryError}
          </p>
        </Card>
      )}

      {entries && entries.length === 0 && (
        <Card style={{ maxWidth: 480 }}>
          <p style={{ margin: 0, color: "var(--text-muted)" }}>
            Queue is empty. Nothing is currently waiting to be delivered by Postfix.
          </p>
        </Card>
      )}

      {entries && entries.length > 0 && (
        <table style={tableStyle}>
          <thead>
            <tr>
              {["Queue ID", "Sender", "Recipients", "Age", "Status", "Actions"].map((label) => (
                <th key={label} style={thStyle}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const badge = statusFor(entry.queue_name);
              return (
                <tr key={entry.queue_id}>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{entry.queue_id}</td>
                  <td style={tdStyle}>{entry.sender}</td>
                  <td style={tdStyle}>{entry.recipients.map((r) => r.address).join(", ")}</td>
                  <td style={{ ...tdStyle, color: "var(--text-muted)" }}>{relativeTime(entry.arrival_time)}</td>
                  <td style={tdStyle}>
                    <StatusBadge status={badge.status} label={badge.label} size="sm" />
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="default" onClick={() => retry.mutate(entry.queue_id)}>
                        Retry
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          setDeleteTarget(entry);
                          setDeleteError(null);
                        }}
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {deleteTarget && (
        <ConfirmModal
          title="Delete this queued message?"
          body="This message will be permanently removed from the Postfix queue and will not be retried."
          confirmLabel="Delete"
          variant="danger"
          confirming={remove.isPending}
          error={deleteError}
          onCancel={() => {
            setDeleteTarget(null);
            setDeleteError(null);
          }}
          onConfirm={() => remove.mutate(deleteTarget.queue_id)}
        />
      )}
    </div>
  );
}
