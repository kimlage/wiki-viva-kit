import { describe, expect, it } from "vitest";
import { applyRuntimeEnv } from "./runtimeConfig";
import type { RuntimeConfig } from "./runtimeConfig";

const staticDemo: RuntimeConfig = {
  apiBase: "",
  snapshotBase: "/sample-snapshot",
  repoLabel: "Wiki Viva Kit demo",
  mode: "static_demo",
  language: "",
  strings: {},
  presentation: {},
  codexEnabled: false
};

describe("runtime config environment boundary", () => {
  it("lets dev:proxy replace every demo provenance field without changing capabilities", () => {
    expect(
      applyRuntimeEnv(staticDemo, {
        VITE_WIKI_API_BASE: "/api/",
        VITE_WIKI_SNAPSHOT_BASE: "/api/snapshot/",
        VITE_WIKI_REPO_LABEL: "",
        VITE_WIKI_RUNTIME_MODE: "local_operator"
      })
    ).toEqual({
      ...staticDemo,
      apiBase: "/api",
      snapshotBase: "/api/snapshot",
      repoLabel: "",
      mode: "local_operator"
    });
  });

  it("keeps the runtime file authoritative when no build override exists", () => {
    expect(applyRuntimeEnv(staticDemo, {})).toEqual(staticDemo);
  });
});
