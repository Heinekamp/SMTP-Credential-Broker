import { Card } from "../design-system/components";

// Temporary placeholder for a module this Stage-7 slice hasn't reached
// yet — swapped out for the real screen in its own commit (see
// docs/implementation-plan.md's Stage 7 build order).
export function ComingSoon({ title }: { title: string }) {
  return (
    <Card style={{ maxWidth: 480 }}>
      <p style={{ margin: 0, color: "var(--text-muted)" }}>{title} is being built in this stage — check back shortly.</p>
    </Card>
  );
}
