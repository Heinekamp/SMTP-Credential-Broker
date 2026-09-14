import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev-server proxy keeps the frontend and API same-site during development,
// so session/CSRF cookies behave exactly as they will in production (served
// by the same FastAPI process) — no CORS configuration needed anywhere.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
