import { createContext, useContext } from "react";

export type ThemeChoice = "dark" | "light" | "system";

export const THEME_STORAGE_KEY = "smtp-relay-theme";

export function readStoredTheme(): ThemeChoice {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    if (value === "dark" || value === "light" || value === "system") return value;
  } catch {
    // Private browsing / blocked storage — fall back to the default below.
  }
  // "dark", not "system" — this console has only ever rendered dark, so an
  // admin whose OS happens to be in light mode must not see the look
  // change out from under them the moment this feature ships. Following
  // the OS is opt-in, chosen explicitly via the theme switcher.
  return "dark";
}

export interface ThemeContextValue {
  theme: ThemeChoice;
  setTheme: (theme: ThemeChoice) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a ThemeProvider");
  return ctx;
}
