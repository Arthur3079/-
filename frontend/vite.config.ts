import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Backend mounts the built SPA at /app (see sonya_web/app.py), so both the
// built index.html asset URLs and the React Router basename need to match
// that prefix. `VITE_BASE_PATH` overrides the default for edge cases like
// mounting at a different prefix in a custom deploy.
const BASE_PATH = process.env.VITE_BASE_PATH ?? "/app/";

export default defineConfig({
  base: BASE_PATH,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
