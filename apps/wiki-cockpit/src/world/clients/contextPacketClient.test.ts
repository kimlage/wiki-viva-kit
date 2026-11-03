import { afterEach, expect, it, vi } from "vitest";
vi.mock("./operatorClient", () => ({ operatorRequest: vi.fn(), operatorPost: vi.fn() }));
import { operatorPost, operatorRequest } from "./operatorClient";
import { clearAdminSession, setAdminSession } from "../../application/adminSession";
import { loadContextPacketCapability, prepareContextPacket } from "./contextPacketClient";
import type { ContextPacketRequest } from "../../data/contextPackets";
const request: ContextPacketRequest = { context_id: "child", approved_revision: "a".repeat(40), content_revision: "a".repeat(40), task: { task_id: "context-work-opaque", goal: "Interpret authorized work", output: "child/result.md", integrator: "independent-integrator", max_bytes: 65536, evidence: [{ ref: "root/work.md", reason: "Selected work", use: "interpretation", classification: "context", expected_document_sha256: "b".repeat(64) }] } };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function result() {
  return { ok: true, mode: "approved", packet: { schema_version: "wiki.task-context/v1", task_id: request.task.task_id, context_id: "child", goal: request.task.goal, output: request.task.output, integrator: request.task.integrator, content_revision: request.content_revision, policy_revision: request.approved_revision, packet_digest: "c".repeat(64), bytes_used: 1024, max_bytes: 65536, selected_text_bytes: 20, coverage: { mode: "explicit_read_set", complete: false, missing: [] }, context: { id: "child", purpose: "Synthetic child", owner: "reviewer", root: "child", lineage: ["root", "child"], boundary: "Policy enforced; folders are not a sandbox." }, enforcement_claim: "Approved policy binding", inputs: [{ kind: "evidence", ref: "root/work.md", section: null, field: null, text: "Authorized work text", byte_length: 20, sha256: "d".repeat(64), document_sha256: "b".repeat(64), revision: request.content_revision, reason: "Selected work" }], declared_read_set: [{ ref: "root/work.md", section: null, field: null, revision: request.content_revision }], required_capabilities: [] } };
}
afterEach(() => { clearAdminSession(); vi.resetAllMocks(); });
it("discovers only the authorized host allowlist with the current memory session and no mutation nonce", async () => {
  setAdminSession("synthetic-token", { sessionId: "s", role: "maintainer", state: "active_partial", expiresAtMs: Date.now() + 60000, ttlS: 60, idleLockS: 60 });
  vi.mocked(operatorRequest).mockResolvedValue(response({ ok: true, schema_version: "wiki.coordination-capability/v1", available: true, contexts: ["child"], policy_revision: request.approved_revision }));
  expect((await loadContextPacketCapability()).available).toBe(true);
  expect(operatorRequest).toHaveBeenCalledWith("/coordination/protected-capability", expect.objectContaining({ cache: "no-store", headers: { "X-Wiki-Admin-Session": "synthetic-token" } }));
  expect(operatorPost).not.toHaveBeenCalled();
});
it("preserves generic binding-or-authorization absence without inventing a context", async () => {
  vi.mocked(operatorRequest).mockResolvedValue(response({ ok: true, schema_version: "wiki.coordination-capability/v1", available: false, reason: "not_available_or_not_authorized" }));
  expect(await loadContextPacketCapability()).toMatchObject({ available: false, reason: "not_available_or_not_authorized" });
});
it("refuses malformed allowlists and policy revisions", async () => {
  for (const change of [{ contexts: [{}] }, { contexts: [] }, { policy_revision: "a branch name" }]) {
    vi.mocked(operatorRequest).mockResolvedValueOnce(response({ ok: true, schema_version: "wiki.coordination-capability/v1", available: true, contexts: ["child"], policy_revision: request.approved_revision, ...change }));
    await expect(loadContextPacketCapability()).rejects.toThrow("context_capability_unknown");
  }
});
it("sends the explicit work selection once, leaving producer resolution to the trusted backend", async () => {
  vi.mocked(operatorPost).mockResolvedValue(response(result()));
  expect((await prepareContextPacket(request)).ok).toBe(true);
  expect(operatorPost).toHaveBeenCalledWith("/coordination/protected/packet", request, { signal: undefined });
  expect(request.task.evidence[0]).not.toHaveProperty("producer");
  expect(operatorPost).toHaveBeenCalledTimes(1);
});
it.each(["task", "context", "revision", "hash", "coverage", "bytes", "output", "read_set"])("does not accept a packet with a mismatched %s claim", async change => {
  const value = result();
  if (change === "task") value.packet.task_id = "other-work";
  if (change === "context") value.packet.context_id = "other-context";
  if (change === "revision") value.packet.content_revision = "e".repeat(40);
  if (change === "hash") value.packet.inputs[0].document_sha256 = "e".repeat(64);
  if (change === "coverage") value.packet.coverage.complete = true;
  if (change === "bytes") value.packet.bytes_used = 1000000;
  if (change === "output") value.packet.output = "other/destination.md";
  if (change === "read_set") value.packet.declared_read_set = [];
  vi.mocked(operatorPost).mockResolvedValue(response(value));
  expect(await prepareContextPacket(request)).toEqual({ ok: false, error_code: "context_packet_unknown", blocker: null });
  expect(operatorPost).toHaveBeenCalledTimes(1);
});
it("retains the safe blocked contract without exposing unrelated error payload fields", async () => {
  const blocker = { action: "prepare packet", target: "selected context", reason: "Selection is not authorized", owner: "context owner", required_action: "Review an explicit connection", interface: null, resume_condition: "Approved connection matches this selection", status: "denied" };
  vi.mocked(operatorPost).mockResolvedValue(response({ ok: false, error_code: "protected_path_detail", secret_detail: "not for the UI", blocker }, 403));
  expect(await prepareContextPacket(request)).toEqual({ ok: false, error_code: "context_packet_blocked", blocker });
  expect(operatorPost).toHaveBeenCalledTimes(1);
});
it("keeps lost and malformed responses unknown without retrying or dropping the work selection", async () => {
  vi.mocked(operatorPost).mockRejectedValueOnce(new Error("lost response"));
  expect((await prepareContextPacket(request)).ok).toBe(false);
  vi.mocked(operatorPost).mockResolvedValueOnce(response({ ok: false, blocker: { status: "resolved" } }, 403));
  expect(await prepareContextPacket(request)).toEqual({ ok: false, error_code: "context_packet_unknown", blocker: null });
  expect(operatorPost).toHaveBeenCalledTimes(2);
});
