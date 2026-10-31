import { afterEach, expect, it, vi } from "vitest";
vi.mock("../../data/runtimeConfig", () => ({ apiUrl: vi.fn(async (path: string) => `/api${path}`) }));
import { loadRuntimeObservations } from "./operationalClient";
import { apiUrl } from "../../data/runtimeConfig";
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
function payload() {
  return { ok: true, schema_version: "wiki_runtime_observations.v1", observed_at: "2026-10-31T12:00:00Z",
    operator: { started_at: "2026-10-31T09:00:00Z", boot_source_commit: null, current_source_commit: null, content_source_commit: null, restart_required: null, server_version: "wiki_web_server.v11", frontend: { status: "not_served", entry_sha256: null, source_commit: null } },
    openclaw: { configured: false, observation_scope: "retained_local_evidence", gateway_status: "not_observed", active_run: null, pending_inputs: null, usage: { status: "not_measured", tokens: null, cost: null }, attempts: [], rules: [], native_observations: [], errors: [] } };
}
it("uses one uncached GET without an admin session or a planning request", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload()))); vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  expect((await loadRuntimeObservations({ signal: controller.signal })).openclaw.active_run).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/runtime/observations", { cache: "no-store", signal: controller.signal });
});
it("keeps an older operator endpoint unavailable and rejects malformed nested evidence", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response("missing", { status: 404 })).mockResolvedValueOnce(new Response(JSON.stringify({ ...payload(), operator: {} }))).mockResolvedValueOnce(new Response(JSON.stringify({ ...payload(), openclaw: { ...payload().openclaw, attempts: [{ attempted_at: 12 }] } })));
  vi.stubGlobal("fetch", fetch);
  await expect(loadRuntimeObservations()).rejects.toThrow("runtime_observation_unavailable");
  await expect(loadRuntimeObservations()).rejects.toThrow("runtime_observation_invalid");
  await expect(loadRuntimeObservations()).rejects.toThrow("runtime_observation_invalid");
  expect(fetch).toHaveBeenCalledTimes(3);
});
it("blocks demo before runtime configuration or transport", async () => {
  vi.stubGlobal("location", { pathname: "/demo/board", search: "" }); const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(loadRuntimeObservations()).rejects.toThrow("read-only demo");
  expect(apiUrl).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});

it("accepts a bounded retained result and refuses malformed result material before rendering", async () => {
  const attempt = { profile: "research", action_id: "action", effect_key: "run", run_id: "run", attempted_at: "2026-10-31T12:00:00Z", result_captured_at: "2026-10-31T12:01:00Z", status: "result_retained",
    result: { excerpt: "Synthetic retained text", text_sha256: "a".repeat(64), truncated: false },
    authorization: { status: "not_observed" }, guard_admission: { status: "not_observed", model: null, effort: null, error_code: null }, review: { status: "not_observed", head: null } };
  const envelope = (row: unknown) => ({ ...payload(), openclaw: { ...payload().openclaw, attempts: [row] } });
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(envelope(attempt))))
    .mockResolvedValueOnce(new Response(JSON.stringify(envelope({ ...attempt, result: { ...attempt.result, excerpt: { html: "invalid" } } }))));
  vi.stubGlobal("fetch", fetch);
  expect((await loadRuntimeObservations()).openclaw.attempts[0].result?.excerpt).toBe("Synthetic retained text");
  await expect(loadRuntimeObservations()).rejects.toThrow("runtime_observation_invalid");
});
