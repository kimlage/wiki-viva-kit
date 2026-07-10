import { beforeEach, describe, expect, it, vi } from "vitest";

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8" }
  });
}

function htmlResponse(): Response {
  return new Response("<!doctype html><html><body>vite fallback</body></html>", {
    status: 200,
    headers: { "content-type": "text/html; charset=utf-8" }
  });
}

describe("snapshot loading", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("fails real loading when /api/snapshot returns HTML instead of JSON", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/wiki-cockpit.config.json") {
        return jsonResponse({ api_base: "/api", mode: "local_operator" });
      }
      if (url.startsWith("/api/snapshot/")) return htmlResponse();
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { loadSnapshotBundle } = await import("./snapshot");
    await expect(loadSnapshotBundle({ demo: false })).rejects.toThrow(/sample fallback is blocked outside \/demo/i);
    await expect(loadSnapshotBundle({ demo: false })).rejects.toThrow(/text\/html/i);
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith("/sample-snapshot"))).toBe(false);
  });

  it("distinguishes current, previous and unsupported snapshot contracts", async () => {
    const { classifySnapshotManifest, SnapshotLoadError } = await import("./snapshot");
    const manifest = (schema_version: string) => ({
      schema_version,
      generated_at: "2026-07-09T00:00:00Z",
      mode: "static",
      source_commit: null,
      repo: {
        repo_id: "fixture",
        language: "en",
        memory_root: "memories",
        default_context: "system",
        karma_enabled: false,
        default_branch: "main",
        branch_prefix: "wiki/"
      },
      files: []
    });
    expect(classifySnapshotManifest(manifest("wiki_web_snapshot.v2"))).toEqual({ state: "current", warnings: [] });
    expect(classifySnapshotManifest(manifest("wiki_web_snapshot.v1"))).toMatchObject({ state: "stale_version" });
    expect(() => classifySnapshotManifest(manifest("wiki_web_snapshot.v99"))).toThrow(SnapshotLoadError);
    try {
      classifySnapshotManifest(manifest("wiki_web_snapshot.v99"));
    } catch (error) {
      expect(error).toMatchObject({ code: "unsupported" });
    }
  });

  it("routes only committed demo scenarios and keeps Genesis stages authoritative", async () => {
    const { demoSnapshotBase } = await import("./snapshot");
    expect(demoSnapshotBase()).toBe("/sample-snapshot");
    expect(demoSnapshotBase({ search: "?demo_scenario=normal_operations" })).toBe("/sample-snapshot");
    expect(demoSnapshotBase({ search: "?demo_scenario=dense_stress" })).toBe(
      "/sample-snapshot/scenarios/dense_stress"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=../../private" })).toBe("/sample-snapshot");
    expect(demoSnapshotBase({ stage: 4, search: "?demo_scenario=dense_stress" })).toBe(
      "/sample-snapshot/stages/4"
    );
    expect(demoSnapshotBase({ scenario: "dense_stress", search: "?demo_scenario=normal_operations" })).toBe(
      "/sample-snapshot/scenarios/dense_stress"
    );
    expect(demoSnapshotBase({ scenario: "../../private" })).toBe("/sample-snapshot");
  });

  it("classifies an incomplete v2 envelope as partial before rendering", async () => {
    const { validateSnapshotEnvelope } = await import("./snapshot");
    const manifest = {
      schema_version: "wiki_web_snapshot.v2",
      snapshot_id: "fixture-1",
      root_page_id: "root",
      bundle_hash: "hash",
      capabilities: ["atomic_envelope"],
      integrity: {},
      generated_at: "2026-07-09T00:00:00Z",
      mode: "static",
      source_commit: null,
      repo: {
        repo_id: "fixture",
        language: "en",
        memory_root: "memories",
        default_context: "system",
        karma_enabled: false,
        default_branch: "main",
        branch_prefix: "wiki/"
      },
      files: []
    };
    await expect(validateSnapshotEnvelope(manifest, {})).rejects.toMatchObject({ code: "partial" });
  });

  it("verifies a content sidecar lazily against the manifest integrity entry", async () => {
    const payload = { ok: true, snapshot_id: "fixture-1" };
    const canonical = JSON.stringify(payload);
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonical)
    );
    const sha256 = [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    const fetchMock = vi.fn(async () => jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    const { loadPageContent, sidecarName } = await import("./snapshot");
    const path = `content/${sidecarName("page-one")}`;
    await expect(
      loadPageContent("page-one", {
        demo: true,
        snapshotSource: "/fixture",
        snapshotId: "fixture-1",
        integrity: { [path]: { sha256, bytes: canonical.length } }
      })
    ).resolves.toEqual(payload);
    await expect(
      loadPageContent("page-one", {
        demo: true,
        snapshotSource: "/fixture",
        snapshotId: "fixture-1",
        integrity: { [path]: { sha256: "0".repeat(64), bytes: canonical.length } }
      })
    ).resolves.toMatchObject({ ok: false, error: expect.stringMatching(/failed integrity/i) });
  });
});
