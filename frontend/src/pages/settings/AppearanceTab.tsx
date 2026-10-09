import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, TextInput } from "../../design-system/components";
import { ApiError, errorMessage } from "../../lib/apiClient";
import { deleteLogo, fetchBranding, updateBranding, uploadLogo } from "../../lib/api/branding";

const DEFAULT_ACCENT = "#72bf44";

const fieldLabelStyle = {
  fontSize: "var(--text-2xs)",
  color: "var(--text-muted)",
  textTransform: "uppercase" as const,
  letterSpacing: "var(--tracking-label)",
  marginBottom: 4,
};

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

// Instance-wide branding (issues #53/#54) — unlike the personal Dark/
// Light/System toggle in the account menu, these apply to every admin
// who logs into this deployment, so they live here alongside the
// other global Settings tabs.
export function AppearanceTab() {
  const queryClient = useQueryClient();
  const { data: branding, dataUpdatedAt: brandingUpdatedAt } = useQuery({ queryKey: ["branding"], queryFn: fetchBranding });
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [accentColor, setAccentColor] = useState(DEFAULT_ACCENT);
  const [saved, setSaved] = useState(false);

  // Adjusts local state when the fetched settings change, without an
  // Effect — https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevBranding, setPrevBranding] = useState(branding);
  if (branding !== prevBranding) {
    setPrevBranding(branding);
    setAccentColor(branding?.accent_color ?? DEFAULT_ACCENT);
  }

  const saveAccent = useMutation({
    mutationFn: (accent_color: string | null) => updateBranding({ accent_color }),
    onSuccess: (data) => {
      queryClient.setQueryData(["branding"], data);
      setSaved(true);
    },
  });

  const [uploadError, setUploadError] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (file: File) => uploadLogo(file),
    onSuccess: (data) => {
      queryClient.setQueryData(["branding"], data);
      setUploadError(null);
    },
    onError: (err) => {
      setUploadError(err instanceof ApiError && typeof err.detail === "string" ? err.detail : "Upload failed.");
    },
  });

  const remove = useMutation({
    mutationFn: () => deleteLogo(),
    onSuccess: (data) => {
      queryClient.setQueryData(["branding"], data);
      setUploadError(null);
    },
    onError: (err) => setUploadError(errorMessage(err, "Could not remove the logo.")),
  });

  const isValidHex = HEX_COLOR_RE.test(accentColor);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
      <Card title="Accent Color">
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Used throughout the UI for primary actions, active states, and highlights. Applies for every admin who
          logs into this deployment.
        </p>

        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <input
            type="color"
            value={isValidHex ? accentColor : DEFAULT_ACCENT}
            onChange={(e) => setAccentColor(e.target.value)}
            style={{ width: 40, height: 32, padding: 0, border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)" }}
          />
          <TextInput
            value={accentColor}
            onChange={(e) => setAccentColor(e.target.value)}
            placeholder={DEFAULT_ACCENT}
            style={{ flex: 1 }}
          />
        </div>
        {!isValidHex && (
          <p style={{ color: "var(--status-fault)", fontSize: "var(--text-2xs)", marginTop: -6, marginBottom: 12 }}>
            Enter a hex color like #3b82f6.
          </p>
        )}

        <div style={fieldLabelStyle}>Preview</div>
        <div style={{ marginBottom: 16 }}>
          <Button
            variant="default"
            style={
              isValidHex
                ? { background: accentColor, borderColor: accentColor, color: "var(--text-on-accent)" }
                : undefined
            }
          >
            Sample Button
          </Button>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <Button
            variant="accent"
            disabled={!isValidHex || saveAccent.isPending}
            onClick={() => {
              setSaved(false);
              saveAccent.mutate(accentColor);
            }}
          >
            {saveAccent.isPending ? "Saving…" : "Save"}
          </Button>
          <Button
            variant="default"
            disabled={saveAccent.isPending}
            onClick={() => {
              setSaved(false);
              setAccentColor(DEFAULT_ACCENT);
              saveAccent.mutate(null);
            }}
          >
            Reset to Default
          </Button>
        </div>
        {saved && !saveAccent.isPending && (
          <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 8, marginBottom: 0 }}>
            Saved.
          </p>
        )}
        {saveAccent.isError && (
          <p style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginTop: 8, marginBottom: 0 }}>
            Could not save.
          </p>
        )}
      </Card>

      <Card title="Logo">
        <p style={{ color: "var(--text-muted)", fontSize: "var(--text-sm)", marginTop: 0 }}>
          Replaces the default wordmark/icon shown in the title bar and on the Login/Setup screens, and doubles
          as the browser tab favicon. PNG, JPEG, or SVG, up to 512 KB.
        </p>

        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <img
            src={branding?.has_custom_logo ? `/api/branding/logo?v=${brandingUpdatedAt}` : "/logo.png"}
            alt=""
            style={{
              height: 48,
              width: 48,
              objectFit: "contain",
              background: "var(--surface-well)",
              borderRadius: "var(--radius-sm)",
              padding: 6,
            }}
          />
          <div style={{ fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
            {branding?.has_custom_logo ? "Custom logo in use" : "Using the default logo"}
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {/* A real button that opens the hidden input — a button nested in a
              <label> doesn't reliably activate the label's control, and the
              hidden input was unreachable by keyboard (#209). */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/svg+xml"
            style={{ display: "none" }}
            tabIndex={-1}
            aria-hidden="true"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
              e.target.value = "";
            }}
          />
          <Button variant="default" disabled={upload.isPending} onClick={() => fileInputRef.current?.click()}>
            {upload.isPending ? "Uploading…" : "Upload Logo"}
          </Button>
          {branding?.has_custom_logo && (
            <Button variant="warn" onClick={() => remove.mutate()} disabled={remove.isPending}>
              {remove.isPending ? "Removing…" : "Remove"}
            </Button>
          )}
        </div>
        {uploadError && (
          <p style={{ color: "var(--status-fault)", fontSize: "var(--text-sm)", marginTop: 8, marginBottom: 0 }}>
            {uploadError}
          </p>
        )}
      </Card>
    </div>
  );
}
