import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Checkbox } from "../../design-system/components";
import { getSenderPermissions, grantSenderPermission, revokeSenderPermission } from "../../lib/api/senders";

// Design handoff §6's "Allowed local users" screen — its own screen, not a
// tab bolted onto the sender. Toggled immediately on click (a check is a
// grant), no separate Save step.
export function SenderPermissions() {
  const params = useParams<{ id: string }>();
  const senderId = Number(params.id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const queryKey = ["senders", senderId, "permissions"];
  const { data } = useQuery({ queryKey, queryFn: () => getSenderPermissions(senderId) });

  const toggle = useMutation({
    mutationFn: ({ localUserId, allowed }: { localUserId: number; allowed: boolean }) =>
      allowed ? grantSenderPermission(senderId, localUserId) : revokeSenderPermission(senderId, localUserId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["senders"] });
    },
  });

  return (
    <Card style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0, marginBottom: 4 }}>
        Sender: {data?.sender.address}
      </h1>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0, marginBottom: 16 }}>
        Allowed local users
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {(data?.local_users ?? []).map((user) => (
          <label
            key={user.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 12px",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
            }}
          >
            <Checkbox
              checked={user.allowed}
              onChange={(e) => toggle.mutate({ localUserId: user.id, allowed: e.target.checked })}
            />
            <div>
              <div style={{ fontSize: "var(--text-sm)" }}>{user.name}</div>
              <div style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", fontFamily: "var(--font-mono)" }}>
                {user.username}
              </div>
            </div>
          </label>
        ))}
        {data && data.local_users.length === 0 && (
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>No local SMTP users exist yet.</p>
        )}
      </div>

      <Button variant="default" onClick={() => navigate("/senders")} style={{ marginTop: 16 }}>
        Done
      </Button>
    </Card>
  );
}
