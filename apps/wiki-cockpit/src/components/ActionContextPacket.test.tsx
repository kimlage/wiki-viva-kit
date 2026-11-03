// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { Blob as NodeBlob } from "node:buffer";
import exportFixture from "../data/fixtures/context-packet-export.json";
import { ActionContextPacket } from "./ActionContextPacket";
import { beginAdminSessionRevocation, clearAdminSession, setAdminSession } from "../application/adminSession";
import type { ContextPacket, ContextPacketPort, ContextPacketRequest, ContextPacketResult } from "../data/contextPackets";
import type { PageRecord } from "../types";
const page = { id: "private-global-work-id", title: "PRIVATE GLOBAL GOAL", path: "root/work.md", context: "display-label-is-not-owner", content_sha256: "b".repeat(64), work: { next_action: "PRIVATE NEXT STEP", owner_ref: "legacy-profile" } } as unknown as PageRecord;
const available = { ok: true as const, schema_version: "wiki.coordination-capability/v1" as const, available: true as const, contexts: ["child"], policy_revision: "a".repeat(40) };
const unavailable = { ok: true as const, schema_version: "wiki.coordination-capability/v1" as const, available: false as const, reason: "not_available_or_not_authorized" as const };
function packet(request: ContextPacketRequest): ContextPacket {
  return { schema_version: "wiki.task-context/v1", task_id: request.task.task_id, context_id: request.context_id, goal: request.task.goal, output: request.task.output, integrator: request.task.integrator, content_revision: request.content_revision, policy_revision: request.approved_revision, packet_digest: "c".repeat(64), bytes_used: 2048, max_bytes: request.task.max_bytes, selected_text_bytes: 24, coverage: { mode: "explicit_read_set", complete: false, missing: ["Other evidence not selected"] }, context: { id: "child", purpose: "Synthetic child", owner: "reviewer", root: "child", lineage: ["root", "child"], boundary: "The folder does not provide an execution sandbox." }, enforcement_claim: "Approved policy binding", inputs: [{ kind: "evidence", ref: page.path, section: null, field: null, text: "Authorized work <script>text</script>", byte_length: 24, sha256: "d".repeat(64), document_sha256: page.content_sha256!, revision: request.content_revision, reason: "Selected work" }], declared_read_set: [{ ref: page.path, section: null, field: null, revision: request.content_revision }], required_capabilities: [] };
}
function setup(options: { unavailable?: boolean; disabled?: boolean; prepare?: ContextPacketPort["preparePacket"] } = {}) {
  const reader = { loadCapability: vi.fn().mockResolvedValue(options.unavailable ? unavailable : available), preparePacket: options.prepare || vi.fn(async request => ({ ok: true as const, mode: "approved" as const, packet: packet(request) })) };
  render(<ActionContextPacket reader={reader} page={page} language="en" disabled={options.disabled} />);
  return reader;
}
async function prepare() {
  await screen.findByLabelText("Output destination");
  fireEvent.change(screen.getByLabelText("Output destination"), { target: { value: "child/result.md" } });
  fireEvent.click(screen.getByRole("button", { name: "Read approved context for this work" }));
}
afterEach(() => { cleanup(); clearAdminSession(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("makes unavailable binding or authority explicit without reading protected content", async () => {
  const reader = setup({ unavailable: true });
  expect(await screen.findByText(/Access or configuration is unavailable/)).toBeTruthy();
  expect(screen.queryByLabelText("Authorized context")).toBeNull();
  expect(reader.preparePacket).not.toHaveBeenCalled();
  expect(document.body.textContent).not.toMatch(/authenticate|login|log in/i);
});
it("does not call the protected route from a read-only view", () => {
  const reader = setup({ disabled: true });
  expect(screen.getByText("Protected context is unavailable in this view.")).toBeTruthy();
  expect(reader.loadCapability).not.toHaveBeenCalled(); expect(reader.preparePacket).not.toHaveBeenCalled();
});
it("selects the actual work page and hash without forwarding its title, goal, profile or guessed owner", async () => {
  const reader = setup();
  const button = await screen.findByRole("button", { name: "Read approved context for this work" });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  await prepare();
  await screen.findByText(/Context assembled for this work/);
  const request = vi.mocked(reader.preparePacket).mock.calls[0][0];
  expect(request.task.task_id).toMatch(/^context-work-/);
  expect(request.task.task_id).not.toBe(page.id);
  expect(JSON.stringify(request)).not.toMatch(/PRIVATE GLOBAL GOAL|PRIVATE NEXT STEP|legacy-profile|display-label-is-not-owner|private-global-work-id/);
  expect(request.task.evidence).toEqual([{ ref: page.path, expected_document_sha256: page.content_sha256, reason: expect.any(String), use: "interpretation", classification: "context" }]);
  expect(request.approved_revision).toBe(available.policy_revision); expect(request.content_revision).toBe(available.policy_revision);
  expect(request.task.output).toBe("child/result.md");
  expect(screen.getByText(/broader coverage remains incomplete/)).toBeTruthy();
  expect(screen.getByText("Authorized work <script>text</script>").tagName).toBe("PRE");
  expect(screen.getByText(/execution and integration require their own evidence/)).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
});
it.each(["pending", "denied", "uncertain"] as const)("shows actionable %s blockers with no invented link, owner or retry", async status => {
  const blocker = { action: "Prepare context packet", target: "Selected context", reason: "Connection requires an explicit decision", owner: "Authorized context owner", required_action: "Review this exact selection", interface: "Operator thread, context request step", resume_condition: "Approved connection and document hash verified", status };
  const preparePacket = vi.fn().mockResolvedValue({ ok: false, error_code: "context_packet_blocked", blocker });
  setup({ prepare: preparePacket }); await prepare();
  for (const value of Object.values(blocker).filter(value => value !== status)) expect(await screen.findByText(value)).toBeTruthy();
  expect(screen.getByText(status[0].toUpperCase() + status.slice(1))).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull(); expect(screen.queryByText(/Context assembled/)).toBeNull();
  expect(preparePacket).toHaveBeenCalledTimes(1);
  expect(preparePacket.mock.calls[0][0].task.evidence[0]).not.toHaveProperty("producer");
});
it("keeps an unknown response distinct from success", async () => {
  const preparePacket = vi.fn().mockRejectedValue(new Error("offline"));
  setup({ prepare: preparePacket }); await prepare();
  expect(await screen.findByText(/Packet result unknown/)).toBeTruthy();
  expect(screen.queryByText(/Context assembled/)).toBeNull(); expect(preparePacket).toHaveBeenCalledTimes(1);
});
it("drops previously observed packet and capability when the local session is revoked", async () => {
  setAdminSession("synthetic", { sessionId: "s", role: "maintainer", state: "active_partial", expiresAtMs: Date.now()+60000, ttlS: 60, idleLockS: 60 });
  const reader = setup(); await prepare(); await screen.findByText(/Context assembled/);
  reader.loadCapability.mockResolvedValue(unavailable);
  act(() => beginAdminSessionRevocation());
  await screen.findByText(/Access or configuration is unavailable/);
  expect(screen.queryByText(/Context assembled/)).toBeNull();
});
it("does not use a late packet response after the selected work changes", async () => {
  let finish!: (result: ContextPacketResult) => void; let requested!: ContextPacketRequest;
  const preparePacket = vi.fn((request: ContextPacketRequest) => { requested = request; return new Promise<ContextPacketResult>(resolve => { finish = resolve; }); });
  const reader = setup({ prepare: preparePacket }); await prepare();
  cleanup(); render(<ActionContextPacket key="new-work" reader={reader} page={{ ...page, id: "another-work", path: "child/another.md" }} language="en" />);
  await act(async () => finish({ ok: true, mode: "approved", packet: packet(requested) }));
  await screen.findByLabelText("Output destination"); expect(screen.queryByText(/Context assembled/)).toBeNull();
  expect((screen.getByLabelText("Output destination") as HTMLInputElement).value).toBe("");
});

function downloadMocks() {
  vi.stubGlobal("crypto", { subtle: webcrypto.subtle, randomUUID: () => "00000000-0000-4000-8000-000000000000" });
  vi.stubGlobal("Blob", NodeBlob);
  const create = vi.fn((_blob: Blob) => "blob:synthetic-packet");
  const revoke = vi.fn();
  class DownloadURL extends URL {}
  Object.defineProperties(DownloadURL, { createObjectURL: { value: create }, revokeObjectURL: { value: revoke } });
  vi.stubGlobal("URL", DownloadURL);
  const anchors: HTMLAnchorElement[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function(this: HTMLAnchorElement) { anchors.push(this); });
  return { create, revoke, anchors };
}
it("keeps revisions, hashes, requested integrator and byte limits inside technical details", async () => {
  setup(); await screen.findByLabelText("Output destination");
  expect(screen.getByText(available.policy_revision).closest("details")?.open).toBe(false);
  expect(screen.getByText(page.content_sha256!).closest("details")?.open).toBe(false);
  expect(screen.getByText("Requested integrator role: independent-integrator").closest("details")?.open).toBe(false);
  expect(screen.getByLabelText("Packet limit (bytes)").closest("details")?.open).toBe(false);
  expect(screen.getByLabelText("Authorized context").closest("details")).toBeNull();
  expect(screen.getByLabelText("Output destination").closest("details")).toBeNull();
});
it("downloads the full canonical packet without changing its digest or making another request", async () => {
  const { create, revoke, anchors } = downloadMocks();
  const preparePacket = vi.fn().mockResolvedValue({ ok: true, mode: "approved", packet: exportFixture as ContextPacket });
  setup({ prepare: preparePacket }); await prepare(); await screen.findByText(/Context assembled/);
  fireEvent.click(screen.getByRole("button", { name: "Download context packet (JSON)" }));
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  const bytes = new Uint8Array(await create.mock.calls[0][0].arrayBuffer());
  expect(bytes.length).toBe(exportFixture.bytes_used);
  expect(JSON.parse(new TextDecoder().decode(bytes))).toEqual(exportFixture);
  expect(anchors[0].download).toBe(`context-packet-${exportFixture.packet_digest.slice(0,16)}.json`);
  expect(anchors[0].href).toBe("blob:synthetic-packet");
  expect(anchors[0].isConnected).toBe(false);
  await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:synthetic-packet"));
  expect(preparePacket).toHaveBeenCalledTimes(1);
});
it("shows a verification error and creates no download when packet bytes do not match", async () => {
  const { create, anchors } = downloadMocks();
  const preparePacket = vi.fn().mockResolvedValue({ ok: true, mode: "approved", packet: { ...exportFixture, bytes_used: exportFixture.bytes_used + 1 } as ContextPacket });
  setup({ prepare: preparePacket }); await prepare(); await screen.findByText(/Context assembled/);
  fireEvent.click(screen.getByRole("button", { name: "Download context packet (JSON)" }));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be verified for download");
  expect(create).not.toHaveBeenCalled(); expect(anchors).toHaveLength(0); expect(preparePacket).toHaveBeenCalledTimes(1);
});
it("discards a pending download when the operator session is revoked", async () => {
  const { create, anchors } = downloadMocks();
  let finish!: (digest: ArrayBuffer) => void;
  const digest = vi.fn(() => new Promise<ArrayBuffer>(resolve => { finish = resolve; }));
  vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000000", subtle: { digest } });
  setAdminSession("synthetic", { sessionId: "s", role: "maintainer", state: "active_partial", expiresAtMs: Date.now()+60000, ttlS: 60, idleLockS: 60 });
  const reader = setup({ prepare: vi.fn().mockResolvedValue({ ok: true, mode: "approved", packet: exportFixture as ContextPacket }) });
  await prepare(); await screen.findByText(/Context assembled/);
  fireEvent.click(screen.getByRole("button", { name: "Download context packet (JSON)" }));
  await waitFor(() => expect(digest).toHaveBeenCalledTimes(1));
  reader.loadCapability.mockResolvedValue(unavailable);
  act(() => beginAdminSessionRevocation());
  await screen.findByText(/Access or configuration is unavailable/);
  await act(async () => finish(Uint8Array.from(exportFixture.packet_digest.match(/../g)!, byte => parseInt(byte,16)).buffer));
  expect(create).not.toHaveBeenCalled(); expect(anchors).toHaveLength(0);
});
