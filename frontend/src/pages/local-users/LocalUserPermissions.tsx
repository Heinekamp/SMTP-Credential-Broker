import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Checkbox } from "../../design-system/components";
import { getLocalUserPermissions, grantLocalUserPermission, revokeLocalUserPermission } from "../../lib/api/localUsers";

// Design handoff §7's "Allowed senders" screen — mirrors §6's Sender
// permissions view exactly (same immediate-commit interaction pattern).
export function LocalUserPermissions() {
  const params = useParams<{ id: string }>();
  const userId = Number(params.id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const queryKey = ["local-users", userId, "permissions"];
  const { data } = useQuery({ queryKey, queryFn: () => getLocalUserPermissions(userId) });

  const toggle = useMutation({
    mutationFn: ({ senderId, allowed }: { senderId: number; allowed: boolean }) =>
      allowed ? grantLocalUserPermission(userId, senderId) : revokeLocalUserPermission(userId, senderId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["local-users"] });
    },
  });

  return (
    <Card style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0, marginBottom: 4 }}>
        User: {data?.user.name}
      </h1>
      <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0, marginBottom: 16 }}>
        Allowed senders
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {(data?.senders ?? []).map((sender) => (
          <label
            key={sender.id}
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", cursor: "pointer" }}
          >
            <Checkbox
              checked={sender.allowed}
              onChange={(e) => toggle.mutate({ senderId: sender.id, allowed: e.target.checked })}
            />
            <span style={{ fontSize: "var(--text-sm)" }}>{sender.address}</span>
          </label>
        ))}
        {data && data.senders.length === 0 && (
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)" }}>No senders exist yet.</p>
        )}
      </div>

      <Button variant="default" onClick={() => navigate("/local-users")} style={{ marginTop: 16 }}>
        Done
      </Button>
    </Card>
  );
}
