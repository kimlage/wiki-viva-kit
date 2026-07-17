// @vitest-environment jsdom

// AdminPlanReview (plan §11, §22.6 frontend side): the dialog renders exactly
// the materialized plan, gates execution on the plan-generated confirmation
// (§9.2), sends plan_id + plan_sha untouched ("what you reviewed is what will
// run"), and shows a server refusal as a typed replan message — never as a
// falsely successful state.

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage, t } from "../data/i18n";
import type { AdminExecuteResult, AdminPlan } from "../data/admin";

const { executeAdminPlan } = vi.hoisted(() => ({
  executeAdminPlan: vi.fn(
    async (): Promise<AdminExecuteResult> => ({ ok: false, errorCode: "operator_unreachable" })
  )
}));

import { AdminPlanReview } from "./AdminPlanReview";

function plan(overrides: Partial<AdminPlan> = {}): AdminPlan {
  return {
    planId: "plan_ab12cd34",
    planSha: `sha256:${"a".repeat(64)}`,
    commandId: "snapshot.rebuild",
    title: "Rebuild the published web snapshot",
    riskLevel: "derive",
    dryRun: false,
    summary: "Rebuild the derived web snapshot.",
    preconditions: [
      { id: "branch", expected: "wiki/topic" },
      { id: "worktree_fingerprint", expected: "sha256:beef" }
    ],
    effects: {
      filesRead: ["memories"],
      filesWrite: ["data/derived/wiki/web-snapshot"],
      externalCalls: [],
      snapshotInvalidated: true
    },
    diff: null,
    validation: { kind: "deterministic_rebuild" },
    undo: { kind: "restore_previous_snapshot_revision", available: false },
    confirmation: { kind: "simple", text: "RUN snapshot.rebuild" },
    ...overrides
  };
}

function successOutcome() {
  return {
    ok: true as const,
    outcome: {
      planId: "plan_ab12cd34",
      commandId: "snapshot.rebuild",
      status: "success",
      dryRun: false,
      output: { files: ["manifest.json"] },
      affectedPaths: ["data/derived/wiki/web-snapshot"],
      branch: "wiki/topic",
      snapshotInvalidated: true,
      undo: { kind: "restore_previous_snapshot_revision", available: true, previousRevision: "rev-1" }
    }
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  configureLanguage("en");
});

describe("AdminPlanReview — reviewed plan is the executed plan", () => {
  it("renders the contract line, effects, risk and preconditions", () => {
    render(<AdminPlanReview executeAdminPlan={executeAdminPlan} plan={plan()} onClose={() => undefined} />);
    expect(screen.getByText(t("admin.plan.contract"))).toBeTruthy();
    expect(screen.getByText("Rebuild the derived web snapshot.")).toBeTruthy();
    expect(screen.getByText("data/derived/wiki/web-snapshot")).toBeTruthy();
    expect(screen.getByText(t("admin.commands.risk.derive"))).toBeTruthy();
    expect(screen.getByText("branch")).toBeTruthy();
    expect(screen.getByText("worktree_fingerprint")).toBeTruthy();
    expect(screen.getByText(t("admin.plan.effects.snapshotInvalidated"))).toBeTruthy();
  });

  it("simple confirmation: the execute button carries the exact phrase and sends it", async () => {
    executeAdminPlan.mockResolvedValueOnce(successOutcome());
    const reviewed = plan();
    render(<AdminPlanReview executeAdminPlan={executeAdminPlan} plan={reviewed} onClose={() => undefined} />);
    const button = screen.getByRole("button", { name: /RUN snapshot\.rebuild/ });
    fireEvent.click(button);
    await waitFor(() => expect(executeAdminPlan).toHaveBeenCalledTimes(1));
    expect(executeAdminPlan).toHaveBeenCalledWith(reviewed, "RUN snapshot.rebuild");
    expect(await screen.findByText(t("admin.plan.result.success"))).toBeTruthy();
    expect(screen.getByText(t("admin.plan.result.snapshotInvalidated"))).toBeTruthy();
  });

  it("typed confirmation gates execution until the exact phrase is typed", async () => {
    executeAdminPlan.mockResolvedValueOnce(successOutcome());
    const typed = plan({ confirmation: { kind: "typed", text: "PUBLISH snapshot.rebuild" } });
    render(<AdminPlanReview executeAdminPlan={executeAdminPlan} plan={typed} onClose={() => undefined} />);
    const execute = screen.getByRole("button", { name: t("admin.plan.execute") });
    expect((execute as HTMLButtonElement).disabled).toBe(true);
    const input = screen.getByLabelText(
      t("admin.plan.typeToConfirm", { text: "PUBLISH snapshot.rebuild" })
    );
    fireEvent.change(input, { target: { value: "PUBLISH everything" } });
    expect((execute as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input, { target: { value: "PUBLISH snapshot.rebuild" } });
    expect((execute as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(execute);
    await waitFor(() => expect(executeAdminPlan).toHaveBeenCalledTimes(1));
    expect(executeAdminPlan).toHaveBeenCalledWith(typed, "PUBLISH snapshot.rebuild");
  });

  it("a read plan executes with no confirmation at all", async () => {
    executeAdminPlan.mockResolvedValueOnce(successOutcome());
    const read = plan({
      riskLevel: "read",
      effects: { filesRead: [".git"], filesWrite: [], externalCalls: [], snapshotInvalidated: false },
      confirmation: { kind: "none", text: null }
    });
    render(<AdminPlanReview executeAdminPlan={executeAdminPlan} plan={read} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: t("admin.plan.execute") }));
    await waitFor(() => expect(executeAdminPlan).toHaveBeenCalledWith(read, null));
  });

  it("shows a stale refusal as a typed replan message, never a result (§9.3)", async () => {
    executeAdminPlan.mockResolvedValueOnce({
      ok: false,
      errorCode: "admin_plan_stale",
      failedPreconditions: ["worktree_fingerprint"]
    });
    render(<AdminPlanReview executeAdminPlan={executeAdminPlan} plan={plan()} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /RUN snapshot\.rebuild/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(t("admin.plan.error.admin_plan_stale"));
    expect(alert.textContent).toContain("worktree_fingerprint");
    expect(alert.textContent).toContain(t("admin.plan.replanHint"));
    expect(screen.queryByText(t("admin.plan.result.success"))).toBeNull();
  });

  it("Escape closes the dialog without executing", () => {
    const onClose = vi.fn();
    render(<AdminPlanReview executeAdminPlan={executeAdminPlan} plan={plan()} onClose={onClose} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(executeAdminPlan).not.toHaveBeenCalled();
  });
});
