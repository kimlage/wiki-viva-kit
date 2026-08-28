import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

describe("snapshot loading", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("revalidates after delayed runtime config and never reads a custom operator base in demo", async () => {
    const location = { pathname: "/w/radar", search: "" };
    const calls: string[] = [];
    vi.stubGlobal("location", location);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url === "/wiki-cockpit.config.json") {
        location.pathname = "/demo/world";
        return jsonResponse({ api_base: "/operator", snapshot_base: "/operator/snapshot", mode: "local_operator" });
      }
      throw new Error(`operator request escaped after demo crossing: ${url}`);
    }));

    const { loadSnapshotBundle } = await import("./snapshot");
    await expect(loadSnapshotBundle({ demo: false })).rejects.toThrow(/read-only demo/);
    expect(calls).toEqual(["/wiki-cockpit.config.json"]);
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

  it("loads the live operator boot through one aggregate snapshot request", async () => {
    const calls: string[] = [];
    const coreFiles = [
      "operations.json", "graph.json", "pages.json", "actions.json",
      "freshness.json", "gates.json", "git.json", "timeline.json",
      "diff.json", "sources.json", "decisions.json", "ingestion.json",
      "quality.json", "commands.json"
    ];
    const aggregate = Object.fromEntries(coreFiles.map((name) => [name, {}]));
    aggregate["manifest.json"] = {
      schema_version: "wiki_web_snapshot.v1",
      capabilities: [],
      repo: { repo_id: "aggregate-fixture" }
    };
    vi.stubGlobal("location", { pathname: "/w/radar", search: "" });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url === "/wiki-cockpit.config.json") {
        return jsonResponse({ api_base: "/api", mode: "local_operator" });
      }
      if (url === "/api/snapshot/boot") return jsonResponse(aggregate);
      throw new Error(`unexpected fetch ${url}`);
    }));

    const { loadSnapshotBundle } = await import("./snapshot");
    const loaded = await loadSnapshotBundle({ demo: false });
    expect(loaded.bundle.manifest.repo.repo_id).toBe("aggregate-fixture");
    expect(calls).toEqual([
      "/wiki-cockpit.config.json",
      "/api/snapshot/boot"
    ]);
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
    expect(demoSnapshotBase({ search: "?demo_scenario=walking_skeleton" })).toBe(
      "/sample-snapshot/scenarios/walking_skeleton"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=dense_stress" })).toBe(
      "/sample-snapshot/scenarios/dense_stress"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=source_lifecycle" })).toBe(
      "/sample-snapshot/scenarios/source_lifecycle"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=failures" })).toBe(
      "/sample-snapshot/scenarios/failures"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=compatibility" })).toBe(
      "/sample-snapshot/scenarios/compatibility"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=accessibility" })).toBe(
      "/sample-snapshot/scenarios/accessibility"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=study_research_showcase" })).toBe(
      "/sample-snapshot/scenarios/study_research_showcase"
    );
    expect(demoSnapshotBase({ search: "?demo_scenario=personal_finance_showcase" })).toBe(
      "/sample-snapshot/scenarios/personal_finance_showcase"
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

  it("accepts an empty root only for a declared Genesis stage zero fixture", async () => {
    const { isDeclaredGenesisEmptyWorld } = await import("./snapshot");
    const manifest = {
      schema_version: "wiki_web_snapshot.v2",
      root_page_id: null,
      capabilities: ["empty_world_compat"],
      fixture: { genesis_stage: 0 }
    } as Parameters<typeof isDeclaredGenesisEmptyWorld>[0];

    expect(isDeclaredGenesisEmptyWorld(manifest, [])).toBe(true);
    expect(
      isDeclaredGenesisEmptyWorld(
        { ...manifest, fixture: { genesis_stage: 1 } },
        []
      )
    ).toBe(false);
    expect(
      isDeclaredGenesisEmptyWorld(
        { ...manifest, fixture: undefined },
        []
      )
    ).toBe(false);
    expect(
      isDeclaredGenesisEmptyWorld(
        { ...manifest, root_page_id: "root" },
        []
      )
    ).toBe(false);
    expect(
      isDeclaredGenesisEmptyWorld(
        manifest,
        [{ id: "root" }] as Parameters<typeof isDeclaredGenesisEmptyWorld>[1]
      )
    ).toBe(false);
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

  it("binds live page content reads to the rendered snapshot revision", async () => {
    const calls: string[] = [];
    let contentPayload: Record<string, unknown> = {
      ok: true,
      snapshot_id: "fixture-A/1"
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url === "/wiki-cockpit.config.json") {
        return jsonResponse({ api_base: "/api", mode: "local_operator" });
      }
      if (url === "/api/pages/page-one/content?snapshot_id=fixture-A%2F1") {
        return jsonResponse(contentPayload);
      }
      throw new Error(`unexpected fetch ${url}`);
    }));

    const { loadPageContent } = await import("./snapshot");
    await expect(
      loadPageContent("page-one", { snapshotId: "fixture-A/1" })
    ).resolves.toMatchObject({ ok: true, snapshot_id: "fixture-A/1" });
    contentPayload = {
      ok: false,
      error: "page changed since snapshot; refresh required",
      error_code: "snapshot_revision_mismatch",
      snapshot_id: "fixture-B/1",
      expected_snapshot_id: "fixture-A/1"
    };
    await expect(
      loadPageContent("page-one", { snapshotId: "fixture-A/1" })
    ).resolves.toMatchObject({
      ok: false,
      error_code: "snapshot_revision_mismatch",
      snapshot_id: "fixture-B/1",
      expected_snapshot_id: "fixture-A/1"
    });
    expect(calls).toEqual([
      "/wiki-cockpit.config.json",
      "/api/pages/page-one/content?snapshot_id=fixture-A%2F1",
      "/api/pages/page-one/content?snapshot_id=fixture-A%2F1"
    ]);
  });

  it("loads and integrity-checks temporal history only when Chronoscope asks for it", async () => {
    const temporalFingerprint = "a".repeat(64);
    const emptyRange = { from: null, to: null, from_precision: null, to_precision: null, event_count: 0, dated_count: 0, undated_count: 0, basis: "full_result" };
    const temporal = {
      schema_version: "wiki_temporal_graph.v1",
      event_schema_version: "wiki_temporal_event.v1",
      repo_id: "fixture",
      revision: `sha256:${temporalFingerprint}`,
      generated_at: "2026-07-11T00:00:00Z",
      event_count: 0,
      total_count: 0,
      returned_count: 0,
      truncated: false,
      next_cursor: null,
      page: { offset: 0, limit: 0, remaining_count: 0, fingerprint: temporalFingerprint },
      range: emptyRange,
      returned_range: { ...emptyRange, basis: "returned_page" },
      summary: { scope: "full_result", event_count: 0, by_kind: {}, by_context: {}, conflict_count: 0, imprecise_count: 0, diagnostic_count: 0 },
      diagnostics: [],
      events: []
    };
    const canonical = canonicalJson(temporal);
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonical)
    );
    const sha256 = [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    const manifest = {
      schema_version: "wiki_web_snapshot.v2",
      snapshot_id: "fixture-lazy-temporal",
      capabilities: ["temporal_graph"],
      versions: { temporal_graph: "wiki_temporal_graph.v1", temporal_event: "wiki_temporal_event.v1" },
      integrity: { "temporal_graph.json": { sha256, bytes: canonical.length } }
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/fixture/temporal_graph.json") return jsonResponse(temporal);
      if (url === "/fixture/manifest.json") return jsonResponse(manifest);
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { loadTemporalGraphForBundle } = await import("./snapshot");
    const bundle = {
      manifest,
      temporalGraphSource: { base: "/fixture", operatorBoundary: false }
    } as unknown as Parameters<typeof loadTemporalGraphForBundle>[0];
    await expect(loadTemporalGraphForBundle(bundle)).resolves.toEqual(temporal);
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      "/fixture/temporal_graph.json",
      "/fixture/manifest.json"
    ]);

    bundle.manifest.integrity!["temporal_graph.json"].sha256 = "0".repeat(64);
    await expect(loadTemporalGraphForBundle(bundle)).rejects.toMatchObject({ code: "integrity" });
  });
});
