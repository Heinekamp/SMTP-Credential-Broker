import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Switch } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { ConfirmModal } from "../../components/ConfirmModal";
import { ApiError } from "../../lib/apiClient";
import { listUpstreamAccounts } from "../../lib/api/upstreamAccounts";
import { deleteSender, deleteSenderPrecheck, listSenders, updateSender, type Sender } from "../../lib/api/senders";

const QUERY_KEY = ["senders"];

export function SendersList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: senders, isLoading, isError } = useQuery({ queryKey: QUERY_KEY, queryFn: listSenders });
  const { data: upstreamAccounts } = useQuery({ queryKey: ["upstream-accounts"], queryFn: listUpstreamAccounts });

  const [disableTarget, setDisableTarget] = useState<Sender | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Sender | null>(null);
  const [deletePrecheck, setDeletePrecheck] = useState<string[] | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const toggleEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateSender(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteSender(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDeleteTarget(null);
      setDeletePrecheck(null);
      setDeleteError(null);
    },
    onError: (err) => {
      // Deleting a sender is expected to always succeed (permission
      // grants cascade away) — this is a safety net for anything
      // unexpected, not a normally-reachable path.
      setDeleteError(
        err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Could not delete this sender.",
      );
    },
  });

  async function openDeleteModal(sender: Sender) {
    const precheck = await deleteSenderPrecheck(sender.id);
    setDeleteTarget(sender);
    setDeletePrecheck(precheck.allowed_local_user_names);
    setDeleteError(null);
  }

  const accountById = new Map((upstreamAccounts ?? []).map((a) => [a.id, a]));

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, margin: 0 }}>Senders</h1>
        <Button variant="accent" onClick={() => navigate("/senders/new")}>
          + Add Sender
        </Button>
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
          <p style={{ margin: 0, fontWeight: 600 }}>Couldn't load senders.</p>
          <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
            This is a connectivity/API issue, not a sign that there's no data.
          </p>
        </Card>
      )}

      {senders && senders.length === 0 && (
        <Card style={{ maxWidth: 480, textAlign: "center" }}>
          <p style={{ color: "var(--text-muted)" }}>
            No senders yet. A sender is an address that sends through one of your upstream accounts.
          </p>
          <Button variant="accent" onClick={() => navigate("/senders/new")}>
            + Add Sender
          </Button>
        </Card>
      )}

      {senders && senders.length > 0 && (
        <table style={tableStyle}>
          <thead>
            <tr>
              {["Address", "Upstream Account", "Status", "Allowed Users", "Actions"].map((label) => (
                <th key={label} style={thStyle}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {senders.map((sender) => {
              const account = accountById.get(sender.upstream_account_id);
              return (
                <tr key={sender.id}>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>{sender.address}</td>
                  <td style={tdStyle}>
                    {account ? (
                      <button
                        type="button"
                        onClick={() => navigate(`/upstream-accounts/${account.id}/edit`)}
                        style={linkButtonStyle}
                      >
                        {account.name}
                      </button>
                    ) : (
                      "—"
                    )}
                    {account && (
                      <div style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>{account.host}</div>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <Switch
                      checked={sender.enabled}
                      onChange={(checked) => {
                        if (checked) {
                          toggleEnabled.mutate({ id: sender.id, enabled: true });
                        } else {
                          setDisableTarget(sender);
                        }
                      }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <button
                      type="button"
                      onClick={() => navigate(`/senders/${sender.id}/permissions`)}
                      style={linkButtonStyle}
                    >
                      {sender.allowed_local_user_count} allowed
                    </button>
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="default" onClick={() => navigate(`/senders/${sender.id}/edit`)}>
                        Edit
                      </Button>
                      <Button variant="default" onClick={() => navigate(`/senders/${sender.id}/permissions`)}>
                        Permissions
                      </Button>
                      <Button variant="danger" onClick={() => openDeleteModal(sender)}>
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

      {disableTarget && (
        <ConfirmModal
          title={`Disable "${disableTarget.address}"?`}
          body="Local users depending on this sender will be unable to send as this address immediately until it is re-enabled."
          confirmLabel="Disable"
          variant="danger"
          confirming={toggleEnabled.isPending}
          onCancel={() => setDisableTarget(null)}
          onConfirm={() => {
            toggleEnabled.mutate({ id: disableTarget.id, enabled: false }, { onSuccess: () => setDisableTarget(null) });
          }}
        />
      )}

      {deleteTarget && deletePrecheck && (
        <ConfirmModal
          title={`Delete "${deleteTarget.address}"?`}
          body={
            deletePrecheck.length === 0
              ? "No local users are currently allowed to use this sender."
              : `${deletePrecheck.length} local user(s) currently allowed to use this sender will lose that grant: ${deletePrecheck.join(", ")}`
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
