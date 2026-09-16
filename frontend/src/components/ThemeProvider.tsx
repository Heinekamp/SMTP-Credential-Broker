import { useEffect, useMemo, useState, type ReactNode } from "react";

import { readStoredTheme, ThemeContext, type ThemeChoice, THEME_STORAGE_KEY } from "../lib/theme";

// Personal, per-browser preference (issue #52) — deliberately not a
// server-side setting, so it behaves like an OS appearance toggle:
// instant, unsaved, and independent of who else logs into this
// deployment.
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readStoredTheme);

  useEffect(() => {
    if (theme === "system") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = theme;
    }
  }, [theme]);

  function setTheme(next: ThemeChoice) {
    setThemeState(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Nothing to do if storage is unavailable — the choice still
      // applies for the rest of this page session.
    }
  }

  const value = useMemo(() => ({ theme, setTheme }), [theme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
