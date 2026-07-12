import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
// The production policy is executable Node ESM and intentionally shared with
// the release runner instead of being reimplemented in TypeScript.
// @ts-expect-error -- the local policy module has no published declaration.
import { assertInternalReleaseBuildEnvironment } from "./scripts/release-build-policy.mjs";

const appRoot = fileURLToPath(new URL(".", import.meta.url));
const runtimeConfigPath = fileURLToPath(new URL("./public/wiki-cockpit.config.json", import.meta.url));

function localOperatorRuntimeConfig(): Record<string, unknown> {
  const parsed = JSON.parse(readFileSync(runtimeConfigPath, "utf8")) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("public runtime config must be a JSON object");
  }
  const base = parsed as Record<string, unknown>;
  const codex = base.codex && typeof base.codex === "object" && !Array.isArray(base.codex)
    ? base.codex as Record<string, unknown>
    : {};
  return {
    ...base,
    api_base: "/api",
    snapshot_base: "/api/snapshot",
    repo_label: "",
    mode: "local_operator",
    codex: { ...codex, enabled: true }
  };
}

function operatorRuntimeConfig(enabled: boolean): Plugin {
  return {
    name: "wiki-cockpit-operator-runtime-config",
    configureServer(server) {
      if (!enabled) return;
      server.middlewares.use((request, response, next) => {
        const pathname = new URL(request.url || "/", "http://127.0.0.1").pathname;
        if (pathname !== "/wiki-cockpit.config.json") {
          next();
          return;
        }
        try {
          response.statusCode = 200;
          response.setHeader("content-type", "application/json; charset=utf-8");
          response.setHeader("cache-control", "no-store");
          response.end(`${JSON.stringify(localOperatorRuntimeConfig())}\n`);
        } catch {
          response.statusCode = 500;
          response.setHeader("content-type", "application/json; charset=utf-8");
          response.setHeader("cache-control", "no-store");
          response.end('{"error":"runtime_config_unavailable"}\n');
        }
      });
    }
  };
}

export default defineConfig(({ command }) => {
  if (command === "build") {
    assertInternalReleaseBuildEnvironment(appRoot, process.env);
  }
  const apiProxyEnabled = command === "serve" && process.env.WIKI_COCKPIT_PROXY_API === "1";
  return {
  // Vite must never load app-local .env files. The release build runner also
  // rejects their presence so an ignored file cannot silently affect a build.
  envDir: false,
  plugins: [react(), operatorRuntimeConfig(apiProxyEnabled)],
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
    // Same-origin is the trust boundary for the local operator proxy. Vite's
    // default permits arbitrary loopback origins, which would let another
    // local web app read the nonce through this proxy after Origin is removed
    // upstream. Browser clients on other ports must receive no CORS grant.
    cors: false,
    proxy: apiProxyEnabled
      ? {
          "/api": {
            target: "http://127.0.0.1:8765",
            configure(proxy) {
              // The browser talks same-origin to Vite. Do not forward that
              // frontend Origin as if it were a direct CORS grant request to
              // the local operator; direct cross-origin access is opt-in.
              proxy.on("proxyReq", (proxyRequest) => proxyRequest.removeHeader("origin"));
            }
          }
        }
      : undefined,
    // The operator writes into data/derived (snapshots, work briefs, codex
    // jobs). Those writes must never trigger a dev full-reload — that would wipe
    // in-flight UI state like an open Brief studio.
    watch: {
      ignored: ["**/data/derived/**"]
    }
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    // A private downstream snapshot can be previewed here. Do not make its
    // static JSON readable to unrelated loopback origins by default.
    cors: false
  }
  };
});
