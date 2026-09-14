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
  const [error, setError] = useState<string | null>(null);

  function handleNameChange(value: string) {
    setName(value);
    if (!usernameTouched) setUsername(suggestUsername(value));
  }

  const create = useMutation({
    mutationFn: () => createLocalUser(name, username),
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
