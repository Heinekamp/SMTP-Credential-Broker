import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, TextInput } from "../../design-system/components";
import { createLocalUser } from "../../lib/api/localUsers";

function suggestUsername(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Design handoff §7's Add form: Name -> Username (auto-suggested from
// name, editable) -> a single "Generate Password" button. Nothing else to
// configure before issuing the credential.
export function LocalUserAddForm() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [usernameTouched, setUsernameTouched] = useState(false);
  const [rateLimitPerHour, setRateLimitPerHour] = useState("");
  const [rateLimitBurst, setRateLimitBurst] = useState("");
  const [error, setError] = useState<string | null>(null);

  function handleNameChange(value: string) {
    setName(value);
    if (!usernameTouched) setUsername(suggestUsername(value));
  }

  const create = useMutation({
    mutationFn: () => {
      const hourly = rateLimitPerHour.trim() === "" ? null : Number(rateLimitPerHour);
      // A burst value only means something alongside an hourly limit —
      // clearing the hourly field silently drops any burst value too,
      // rather than submitting a combination the API would reject.
      const burst = hourly === null || rateLimitBurst.trim() === "" ? null : Number(rateLimitBurst);
      return createLocalUser(name, username, hourly, burst);
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["local-users"] });
      navigate(`/local-users/${result.user.id}/reveal`, { state: { password: result.password } });
    },
    onError: () => setError("Could not create this user. The username may already be in use."),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <Card style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600, marginTop: 0 }}>Add Local SMTP User</h1>
      {error && (
        <div role="alert" style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginBottom: 14 }}>
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <label style={labelStyle} htmlFor="lu-name">Name</label>
        <TextInput id="lu-name" value={name} onChange={(e) => handleNameChange(e.target.value)} style={fieldStyle} required />

        <label style={labelStyle} htmlFor="lu-username">Username</label>
        <TextInput
          id="lu-username"
          value={username}
          onChange={(e) => {
            setUsernameTouched(true);
            setUsername(e.target.value);
          }}
          style={fieldStyle}
          required
        />
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -8, marginBottom: 14 }}>
          Auto-suggested from the name — edit if you'd like something different.
        </p>

        <label style={labelStyle} htmlFor="lu-rate-limit">Rate Limit (messages/hour)</label>
        <TextInput
          id="lu-rate-limit"
          type="number"
          min={1}
          placeholder="Unlimited"
          value={rateLimitPerHour}
          onChange={(e) => setRateLimitPerHour(e.target.value)}
          style={fieldStyle}
        />
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -8, marginBottom: 14 }}>
          Blank means unlimited. Over the limit, sends are rejected until the current hour ends — protects a shared
          upstream mailbox from one misbehaving credential.
        </p>

        <label style={labelStyle} htmlFor="lu-rate-limit-burst">Burst Limit (messages in a row)</label>
        <TextInput
          id="lu-rate-limit-burst"
          type="number"
          min={1}
          placeholder="No burst protection"
          value={rateLimitBurst}
          onChange={(e) => setRateLimitBurst(e.target.value)}
          style={fieldStyle}
          disabled={rateLimitPerHour.trim() === ""}
        />
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-2xs)", marginTop: -8, marginBottom: 14 }}>
          {rateLimitPerHour.trim() === ""
            ? "Requires a rate limit above — it paces how fast that limit can be reached, so a haywire credential is throttled within seconds instead of only once the whole hour's quota is gone."
            : "Blank means no extra protection beyond the hourly limit above. Once this many messages go out back-to-back, further sends are throttled — and gradually allowed again — at the pace the hourly limit implies."}
        </p>

        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <Button type="submit" variant="accent" disabled={create.isPending}>
            Generate Password
          </Button>
          <Button type="button" variant="default" onClick={() => navigate("/local-users")}>
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
