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
