import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev-server proxy keeps the frontend and API same-site during development,
// so session/CSRF cookies behave exactly as they will in production (served
// by the same FastAPI process) — no CORS configuration needed anywhere.
// The backend port is overridable (VITE_BACKEND_PORT) so tooling that spins
// up a throwaway backend on a non-default port — scripts/screenshots/ — can
// point here without hand-editing this file each time.
const backendPort = process.env.VITE_BACKEND_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
