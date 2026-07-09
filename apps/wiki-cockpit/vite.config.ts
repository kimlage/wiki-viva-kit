import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const apiProxyEnabled = process.env.WIKI_COCKPIT_PROXY_API === "1";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: /^three$/,
        // Three's package export is one monolithic module. Its source entry
        // preserves module boundaries so the real scene can be split safely.
        replacement: fileURLToPath(new URL("./node_modules/three/src/Three.js", import.meta.url))
      }
    ]
  },
  build: {
    rolldownOptions: {
      output: {
        strictExecutionOrder: true,
        // Split real code instead of relaxing Vite's 500 kB warning. The v8
        // bundle gate measures aggregate initial gzip and every lazy chunk.
        codeSplitting: {
          minSize: 20_000,
          maxSize: 450_000,
          groups: [
            {
              name: "three-runtime",
              test: /node_modules[\\/](three|three-stdlib|@react-three|camera-controls|maath)[\\/]/,
              priority: 30,
              minSize: 20_000,
              maxSize: 420_000,
              entriesAware: true,
              includeDependenciesRecursively: true
            }
          ]
        }
      }
    }
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: apiProxyEnabled ? { "/api": "http://127.0.0.1:8765" } : undefined,
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
