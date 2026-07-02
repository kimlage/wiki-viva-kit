import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765"
    },
    // The operator writes into data/derived (snapshots, work briefs, codex
    // jobs). Those writes must never trigger a dev full-reload — that would wipe
    // in-flight UI state like an open Brief studio.
    watch: {
      ignored: ["**/data/derived/**"]
    }
  },
  preview: {
    host: "127.0.0.1",
    port: 4173
  }
});
