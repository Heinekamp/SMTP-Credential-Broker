import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Select, TextInput } from "../../design-system/components";
import { listUpstreamAccounts } from "../../lib/api/upstreamAccounts";
import { createSender, getSender, updateSender } from "../../lib/api/senders";

const QUERY_KEY = ["senders"];

// Design handoff §6's Add/Edit form: Address, Upstream account Select
// rendered as "<name> — <host>" so the credential choice is never a bare ID.
export function SenderForm() {
  const params = useParams<{ id: string }>();
  const isEdit = params.id !== undefined;
  const senderId = isEdit ? Number(params.id) : undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: accounts } = useQuery({ queryKey: ["upstream-accounts"], queryFn: listUpstreamAccounts });
  const { data: existing } = useQuery({
    queryKey: [...QUERY_KEY, senderId],
    queryFn: () => getSender(senderId!),
    enabled: isEdit,
  });

  const [address, setAddress] = useState("");
  const [upstreamAccountId, setUpstreamAccountId] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (existing) {
      setAddress(existing.address);
      setUpstreamAccountId(existing.upstream_account_id);
    }
  }, [existing]);

  useEffect(() => {
    if (!isEdit && upstreamAccountId === "" && accounts && accounts.length > 0) {
      setUpstreamAccountId(accounts[0].id);
    }
  }, [accounts, isEdit, upstreamAccountId]);

  const save = useMutation({
    mutationFn: () => {
      const input = { address, upstream_account_id: Number(upstreamAccountId) };
      return isEdit ? updateSender(senderId!, input) : createSender(input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      navigate("/senders");
    },
    onError: () => setError("Could not save this sender. The address may already be in use."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate();
  }

  return (
    <Card style={{ maxWidth: 520 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0 }}>
        {isEdit ? "Edit Sender" : "Add Sender"}
      </h1>
      {error && (
        <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 14 }}>
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <label style={labelStyle}>Address</label>
        <TextInput value={address} onChange={(e) => setAddress(e.target.value)} style={fieldStyle} required />

        <label style={labelStyle}>Upstream Account</label>
        <Select
          value={upstreamAccountId}
          onChange={(e) => setUpstreamAccountId(Number(e.target.value))}
          style={{ ...fieldStyle, width: "100%" }}
        >
          {(accounts ?? []).map((account) => (
            <option key={account.id} value={account.id}>
              {account.name} — {account.host}
            </option>
          ))}
        </Select>
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -8, marginBottom: 14 }}>
          This address will send through the selected upstream mailbox's credentials.
        </p>

        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <Button type="submit" variant="accent" disabled={save.isPending || upstreamAccountId === ""}>
            Save
          </Button>
          <Button type="button" variant="default" onClick={() => navigate("/senders")}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

const labelStyle = {
  display: "block",
  fontSize: "var(--text-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase" as const,
  letterSpacing: "var(--tracking-label)",
  marginBottom: 4,
};

const fieldStyle = { width: "100%", marginBottom: 14 };
