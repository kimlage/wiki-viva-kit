import { afterEach, expect, it, vi } from "vitest";
vi.mock("../../data/runtimeConfig", () => ({ apiUrl: vi.fn(async (path: string) => `/api${path}`) }));
import { loadRuntimeObservations } from "./operationalClient";
import { apiUrl } from "../../data/runtimeConfig";
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });
function payload() {
  return { ok: true, schema_version: "wiki_runtime_observations.v1", observed_at: "2026-10-31T12:00:00Z",
    operator: { started_at: "2026-10-31T09:00:00Z", boot_source_commit: null, current_source_commit: null, content_source_commit: null, restart_required: null, server_version: "wiki_web_server.v11", frontend: { status: "not_served", entry_sha256: null, source_commit: null } } };
}
it("uses one uncached GET for the operator alone without an admin session or a planning request", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload()))); vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  expect((await loadRuntimeObservations({ signal: controller.signal })).operator.restart_required).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/runtime/observations", { cache: "no-store", signal: controller.signal });
});
it("keeps unavailable endpoints and malformed operator observations unavailable", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response("missing", { status: 404 }));
  vi.stubGlobal("fetch", fetch);
  await expect(loadRuntimeObservations()).rejects.toThrow("runtime_observation_unavailable");
  for (const invalid of [ { ...payload(), operator: {} }, { ...payload(), operator: { ...payload().operator, frontend: null } },
    { ...payload(), operator: { ...payload().operator, restart_required: "yes" } }, { ...payload(), ok: false } ]) {
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(invalid)));
    await expect(loadRuntimeObservations()).rejects.toThrow("runtime_observation_invalid");
  }
});
it("blocks demo before runtime configuration or transport", async () => {
  vi.stubGlobal("location", { pathname: "/demo/board", search: "" }); const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(loadRuntimeObservations()).rejects.toThrow("read-only demo");
  expect(apiUrl).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});
