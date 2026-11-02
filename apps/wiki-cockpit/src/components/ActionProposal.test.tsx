// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { AdminPort } from "../application/ports";
import type { AdminPlan } from "../data/admin";
import { configureLanguage, t } from "../data/i18n";
import { clearAdminSession } from "../application/adminSession";
import { ActionProposal } from "./ActionProposal";

afterEach(() => { cleanup(); clearAdminSession(); });
const proposal = { status: "prepared" as const, head: "e".repeat(40), proposal_head: "e".repeat(40), approved_base: "a".repeat(40), branch: "wiki/proposal", material_path: "data/derived/proposal.json", material_sha256: "f".repeat(64) };
function setup(over: Partial<React.ComponentProps<typeof ActionProposal>> = {}) {
  configureLanguage("en");
  const plan: AdminPlan = { planId: "plan-exact", planSha: "sha256:" + "b".repeat(64), commandId: "wiki.proposal.prepare", title: "Prepare proposal", riskLevel: "proposal_write", dryRun: false, summary: "One proposal", preconditions: [], effects: { filesRead: [proposal.material_path], filesWrite: [], externalCalls: [], snapshotInvalidated: false }, diff: "Reviewed proposal", validation: {}, undo: { available: false, kind: null }, confirmation: { kind: "none", text: null } };
  const admin = { planAdminCommand: vi.fn().mockImplementation(async (id: string) => ({ ok: true, plan: { ...plan, commandId: id } })), executeAdminPlan: vi.fn().mockResolvedValue({ ok: true, outcome: { planId: plan.planId, commandId: plan.commandId, status: "success", dryRun: false, output: { prepared: true, head: proposal.head, proposal }, affectedPaths: [], branch: proposal.branch, snapshotInvalidated: false, undo: { available: false, kind: null } } }), lockAdminSession: vi.fn(), renewAdminSession: vi.fn(), requestAdminChallenge: vi.fn(), unlockAdminSession: vi.fn() } as unknown as AdminPort;
  const refresh = vi.fn();
  render(<ActionProposal admin={admin} actionId="synthetic-action" disabled={false} language="en" refresh={refresh} {...over} />);
  return { admin, plan, refresh };
}
function material() {
  fireEvent.change(screen.getByLabelText("Proposal material path"), { target: { value: proposal.material_path } });
  fireEvent.change(screen.getByLabelText("Material SHA-256"), { target: { value: proposal.material_sha256 } });
}
it("plans exact material and digest before executing, then uses the observed proposal identity", async () => {
  const { admin, plan } = setup();
  material();
  fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  await waitFor(() => expect(admin.planAdminCommand).toHaveBeenCalledWith("wiki.proposal.prepare", { material_path: proposal.material_path, material_sha256: proposal.material_sha256 }));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole("button", { name: t("admin.plan.execute") }));
  await waitFor(() => expect(admin.executeAdminPlan).toHaveBeenCalledWith(plan, null));
  expect((await screen.findAllByText(/Proposal committed locally/)).length).toBeGreaterThan(0);
  fireEvent.click(screen.getAllByRole("button", { name: t("surface.close") })[0]);
  fireEvent.click(screen.getByRole("button", { name: "Review publication of this commit" }));
  await waitFor(() => expect(admin.planAdminCommand).toHaveBeenLastCalledWith("wiki.proposal.publish", { expected_head: proposal.head, operation: "publish_proposal" }));
  expect(admin.executeAdminPlan).toHaveBeenCalledTimes(1);
});
it("preserves failed planning observations without treating refusal as execution", async () => {
  const { admin } = setup();
  vi.mocked(admin.planAdminCommand).mockResolvedValue({ ok: false, errorCode: "admin_invalid_params", preparatoryObservations: ["Proposal metadata was read before refusal."] });
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(await screen.findByText("Proposal metadata was read before refusal.")).toBeTruthy();
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});
it("does not treat a configured view as granted write access", () => {
  const { admin } = setup({ disabled: true }); material();
  fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(admin.planAdminCommand).not.toHaveBeenCalled();
  expect(screen.getByText(/each effect still requires its own reviewed plan/)).toBeTruthy();
});
it("requires the exact independent review and PR before planning integration", async () => {
  const { admin } = setup({ initialProposal: proposal });
  fireEvent.click(screen.getByRole("button", { name: "Review integration of the reviewed PR" }));
  expect(admin.planAdminCommand).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Existing PR number"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Independent review artifact path"), { target: { value: "reviews/exact.md" } });
  fireEvent.change(screen.getByLabelText("Review artifact SHA-256"), { target: { value: "c".repeat(64) } });
  fireEvent.click(screen.getByRole("button", { name: "Review integration of the reviewed PR" }));
  await waitFor(() => expect(admin.planAdminCommand).toHaveBeenCalledWith("wiki.proposal.promote", { expected_head: proposal.head, approved_base: proposal.approved_base, pr: "7", review_path: "reviews/exact.md", review_sha256: "c".repeat(64) }));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});
it("keeps approved content adoption bound to distinct checkout and proposal commits", async () => {
  const { admin } = setup({ initialProposal: { ...proposal, status: "awaiting_adoption", head: "d".repeat(40) } });
  fireEvent.change(screen.getByLabelText("Existing PR number"), { target: { value: "9" } });
  fireEvent.click(screen.getByRole("button", { name: "Review refresh of approved content" }));
  await waitFor(() => expect(admin.planAdminCommand).toHaveBeenCalledWith("wiki.proposal.adopt", { expected_head: "d".repeat(40), proposal_head: proposal.proposal_head, pr: "9" }));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});
it("rejects a mismatched planning response before exposing execution", async () => {
  const { admin, plan } = setup();
  vi.mocked(admin.planAdminCommand).mockResolvedValue({ ok: true, plan: { ...plan, commandId: "wiki.proposal.publish" } });
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(await screen.findByText(/Command unavailable/)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});

it("requires material and a valid digest, and keeps reviewed inputs fixed while the plan is open", async () => {
  const { admin } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(admin.planAdminCommand).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Proposal material path"), { target: { value: proposal.material_path } });
  fireEvent.change(screen.getByLabelText("Material SHA-256"), { target: { value: "changed-digest" } });
  fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(admin.planAdminCommand).not.toHaveBeenCalled();
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  await screen.findByRole("dialog");
  expect((screen.getByLabelText("Proposal material path") as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText("Material SHA-256") as HTMLInputElement).disabled).toBe(true);
  expect(admin.planAdminCommand).toHaveBeenCalledWith("wiki.proposal.prepare", { material_path: proposal.material_path, material_sha256: proposal.material_sha256 });
});

it("does not infer an authenticated session from the availability of local forms", async () => {
  const { admin } = setup();
  vi.mocked(admin.planAdminCommand).mockResolvedValue({ ok: false, errorCode: "admin_session_invalid" });
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(await screen.findByText(/admin_session_invalid/)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});

it.each([
  ["failed", {}], ["uncertain", {}], ["success", { outcome_uncertain: true }]
])("does not advance the proposal or claim completion after %s (%j)", async (status, extra) => {
  const { admin, plan } = setup();
  vi.mocked(admin.executeAdminPlan).mockResolvedValue({ ok: true, outcome: { planId: plan.planId, commandId: plan.commandId, status, dryRun: false, output: { prepared: true, proposal, ...extra }, affectedPaths: [], branch: proposal.branch, snapshotInvalidated: false, undo: { available: false, kind: null } } });
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  fireEvent.click(await screen.findByRole("button", { name: t("admin.plan.execute") }));
  await waitFor(() => expect(admin.executeAdminPlan).toHaveBeenCalledTimes(1));
  expect(screen.queryByText(/Proposal committed locally/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Review publication of this commit" })).toBeNull();
  expect(screen.queryByText(t("admin.plan.executed"))).toBeNull();
  expect(screen.queryByText(t("admin.plan.result.success"))).toBeNull();
  expect(screen.getAllByText(t(status === "failed" ? "admin.plan.result.failed" : "admin.plan.result.uncertain")).length).toBeGreaterThan(0);
});

it("starts fresh after reload without inferring proposal state from a prior command readback", async () => {
  const { admin, refresh } = setup(); material();
  fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  fireEvent.click(await screen.findByRole("button", { name: t("admin.plan.execute") }));
  await screen.findAllByText(/Proposal committed locally/);
  cleanup();
  render(<ActionProposal admin={admin} actionId="synthetic-action" disabled={false} language="en" refresh={refresh} />);
  expect((screen.getByLabelText("Proposal material path") as HTMLInputElement).value).toBe("");
  expect(screen.queryByText(/Proposal committed locally/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Review publication of this commit" })).toBeNull();
  expect(admin.planAdminCommand).toHaveBeenCalledTimes(1);
  expect(admin.executeAdminPlan).toHaveBeenCalledTimes(1);
});

it("keeps material changed on disk as a server refusal requiring fresh review", async () => {
  const { admin } = setup();
  vi.mocked(admin.planAdminCommand).mockResolvedValue({ ok: false, errorCode: "admin_invalid_params", detail: "proposal_material_digest_mismatch" });
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  expect(await screen.findByText(/proposal_material_digest_mismatch/)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});

it("does not construct proposal identity from form inputs when backend projection is absent", async () => {
  const { admin, plan } = setup();
  vi.mocked(admin.executeAdminPlan).mockResolvedValue({ ok: true, outcome: { planId: plan.planId, commandId: plan.commandId, status: "success", dryRun: false, output: { prepared: true, head: proposal.head }, affectedPaths: [], branch: proposal.branch, snapshotInvalidated: false, undo: { available: false, kind: null } } });
  material(); fireEvent.click(screen.getByRole("button", { name: "Review proposal preparation" }));
  fireEvent.click(await screen.findByRole("button", { name: t("admin.plan.execute") }));
  await screen.findByText(/Proposal committed locally/);
  expect(screen.queryByRole("button", { name: "Review publication of this commit" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Review integration of the reviewed PR" })).toBeNull();
});
