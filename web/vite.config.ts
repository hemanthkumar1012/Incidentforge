/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI calls same-origin /api; in development Vite proxies it to forge-api.
// Same-origin keeps CORS closed on the API (FORGE_CORS_ORIGINS stays empty).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": process.env.FORGE_API ?? "http://localhost:8080" } },
  preview: { port: 4173, proxy: { "/api": process.env.FORGE_API ?? "http://localhost:8080" } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
