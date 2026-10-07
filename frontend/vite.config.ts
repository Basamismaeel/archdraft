import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The backend runs on :8000. Proxying /api avoids CORS configuration in v1.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // GitHub Pages serves the site from /<repo>/, so the Pages build sets VITE_BASE.
  base: loadEnv(mode, ".", "VITE_").VITE_BASE ?? "/",
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
}));
