import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, StatusBadge, Switch } from "../../design-system/components";
import { skeletonBarStyle, tableStyle, tdStyle, thStyle } from "../../design-system/table";
import { ConfirmModal } from "../../components/ConfirmModal";
import { ApiError } from "../../lib/apiClient";
import { parseApiDate } from "../../lib/apiDate";
import {
  deleteUpstreamAccount,
  deleteUpstreamAccountPrecheck,
  listUpstreamAccounts,
  updateUpstreamAccount,
  type UpstreamAccount,
} from "../../lib/api/upstreamAccounts";

const QUERY_KEY = ["upstream-accounts"];

function tlsLabel(account: UpstreamAccount): string {
  return account.tls_mode === "starttls" ? `STARTTLS · ${account.port}` : `Implicit TLS · ${account.port}`;
}

function lastTestLabel(account: UpstreamAccount): { status: "idle" | "fault" | "waiting"; label: string } {
  if (!account.last_test_result || account.last_test_result === "unknown") {
    return { status: "waiting", label: "Never tested" };
  }
  return account.last_test_result === "success"
    ? { status: "idle", label: "Passed" }
    : { status: "fault", label: "Failed" };
}

function rateLimitLabel(account: UpstreamAccount): string {
  return account.rate_limit_per_hour === null
    ? "Unlimited"
    : `${account.sent_this_hour}/${account.rate_limit_per_hour} this hour`;
}

export function UpstreamAccountsList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: accounts, isLoading, isError } = useQuery({ queryKey: QUERY_KEY, queryFn: listUpstreamAccounts });

  const [disableTarget, setDisableTarget] = useState<UpstreamAccount | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UpstreamAccount | null>(null);
  const [deletePrecheck, setDeletePrecheck] = useState<string[] | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const toggleEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateUpstreamAccount(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteUpstreamAccount(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDeleteTarget(null);
      setDeletePrecheck(null);
      setDeleteError(null);
    },
    onError: (err) => {
      // Belt-and-suspenders: the precheck below should already prevent
      // this from being reachable, but a sender could be attached in the
      // gap between the precheck fetch and this click.
      setDeleteError(
        err instanceof ApiError && typeof err.detail === "string"
          ? err.detail
          : "Could not delete this account.",
      );
    },
  });

  async function openDeleteModal(account: UpstreamAccount) {
    const precheck = await deleteUpstreamAccountPrecheck(account.id);
    setDeleteTarget(account);
    setDeletePrecheck(precheck.dependent_sender_addresses);
    setDeleteError(null);
  }

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, margin: 0 }}>Upstream Accounts</h1>
        <Button variant="accent" onClick={() => navigate("/upstream-accounts/new")}>
          + Add Upstream Account
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
          <p style={{ margin: 0, fontWeight: 600 }}>Couldn't load upstream accounts.</p>
          <p style={{ margin: "4px 0 0", color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>
            This is a connectivity/API issue, not a sign that there's no data.
          </p>
        </Card>
      )}

      {accounts && accounts.length === 0 && (
        <Card style={{ maxWidth: 480, textAlign: "center" }}>
          <p style={{ color: "var(--text-muted)" }}>
            No upstream accounts yet. Add the externally-hosted SMTP mailboxes this relay will send through.
          </p>
          <Button variant="accent" onClick={() => navigate("/upstream-accounts/new")}>
            + Add Upstream Account
          </Button>
        </Card>
      )}

      {accounts && accounts.length > 0 && (
        <table style={tableStyle}>
          <thead>
            <tr>
              {["Name", "Host", "TLS Mode", "Status", "Last Test", "Rate Limit", "Actions"].map((label) => (
                <th key={label} style={thStyle}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => {
              const lastTest = lastTestLabel(account);
              return (
                <tr key={account.id}>
                  <td style={tdStyle}>{account.name}</td>
                  <td style={tdStyle}>{account.host}</td>
                  <td style={tdStyle}>{tlsLabel(account)}</td>
                  <td style={tdStyle}>
                    <Switch
                      checked={account.enabled}
                      onChange={(checked) => {
                        if (checked) {
                          toggleEnabled.mutate({ id: account.id, enabled: true });
                        } else {
                          setDisableTarget(account);
                        }
                      }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <StatusBadge status={lastTest.status} label={lastTest.label} size="sm" />
                    {account.last_test_at && (
                      <div style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: 2 }}>
                        {parseApiDate(account.last_test_at).toLocaleString()}
                      </div>
                    )}
                  </td>
                  <td style={{ ...tdStyle, color: "var(--text-muted)" }}>{rateLimitLabel(account)}</td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <Button variant="default" onClick={() => navigate(`/upstream-accounts/${account.id}/edit`)}>
                        Edit
                      </Button>
                      <Button variant="default" onClick={() => navigate(`/upstream-accounts/${account.id}/test`)}>
                        Test Connection
                      </Button>
                      <Button variant="danger" onClick={() => openDeleteModal(account)}>
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
          title={`Disable "${disableTarget.name}"?`}
          body="Services depending on this will stop working immediately until it is re-enabled."
          confirmLabel="Disable"
          variant="danger"
          confirming={toggleEnabled.isPending}
          onCancel={() => setDisableTarget(null)}
          onConfirm={() => {
            toggleEnabled.mutate(
              { id: disableTarget.id, enabled: false },
              { onSuccess: () => setDisableTarget(null) },
            );
          }}
        />
      )}

      {deleteTarget && deletePrecheck && (
        <ConfirmModal
          title={`Delete "${deleteTarget.name}"?`}
          body={
            deletePrecheck.length === 0 ? (
              "No senders currently reference this account."
            ) : (
              <>
                This account can't be deleted while senders still use it. Reassign or delete these senders
                first: {deletePrecheck.join(", ")}
              </>
            )
          }
          confirmLabel="Delete"
          variant="danger"
          confirming={remove.isPending}
          confirmDisabled={deletePrecheck.length > 0}
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
