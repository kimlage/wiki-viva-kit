import { describe, expect, it } from "vitest";
import { normalizeRuntimeConfig } from "./runtimeConfig";

describe("runtime config boundary", () => {
  it("normalizes the runtime file without consulting build-time environment", () => {
    expect(
      normalizeRuntimeConfig({
        api_base: "/api/",
        snapshot_base: "/api/snapshot/",
        repo_label: " Operator ",
        mode: "local_operator",
        codex: { enabled: true }
      })
    ).toEqual({
      apiBase: "/api",
      snapshotBase: "/api/snapshot",
      repoLabel: "Operator",
      mode: "local_operator",
      language: "",
      strings: {},
      presentation: { page_types: {}, contexts: {}, trust_colors: {} },
      features: { takezoEasterEgg: true, takezoCompanion: false },
      codexEnabled: true
    });
  });

  it("keeps an explicit empty API base authoritative", () => {
    expect(normalizeRuntimeConfig({ api_base: "", snapshot_base: "/sample/" })).toMatchObject({
      apiBase: "",
      snapshotBase: "/sample"
    });
  });

  it("defaults the takezo presentation flags to egg on, companion off (plan §17.2)", () => {
    expect(normalizeRuntimeConfig({}).features).toEqual({
      takezoEasterEgg: true,
      takezoCompanion: false
    });
  });

  it("honors explicit takezo flag overrides without a rebuild", () => {
    expect(
      normalizeRuntimeConfig({ features: { takezo_easter_egg: false, takezo_companion: true } }).features
    ).toEqual({ takezoEasterEgg: false, takezoCompanion: true });
  });
});
