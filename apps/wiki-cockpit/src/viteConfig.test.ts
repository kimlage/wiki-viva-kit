import type { UserConfig } from "vite";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import viteConfig from "../vite.config";

function developmentConfig(): UserConfig {
  const factory = viteConfig as unknown as (environment: {
    command: "serve";
    mode: string;
    isSsrBuild: boolean;
    isPreview: boolean;
  }) => UserConfig;
  return factory({
    command: "serve",
    mode: "development",
    isSsrBuild: false,
    isPreview: false
  });
}

describe("local browser trust boundary", () => {
  it("does not grant cross-origin reads from other loopback apps", () => {
    const config = developmentConfig();

    expect(config.server?.host).toBe("127.0.0.1");
    expect(config.server?.cors).toBe(false);
    expect(config.preview?.host).toBe("127.0.0.1");
    expect(config.preview?.cors).toBe(false);
    expect(config.envDir).toBe(false);
    expect(config.cacheDir).toBe("tmp/vite-cache");
    expect(config.cacheDir).not.toContain("node_modules");
  });

  it("keeps the snapshot readiness check on the configured dev port", () => {
    const config = developmentConfig();
    const checker = readFileSync(
      new URL("../scripts/check-snapshot-api.mjs", import.meta.url),
      "utf8"
    );

    expect(config.server?.port).toBe(5173);
    expect(checker).toContain(
      `http://127.0.0.1:${config.server?.port}/api/snapshot/pages.json`
    );
  });
});
