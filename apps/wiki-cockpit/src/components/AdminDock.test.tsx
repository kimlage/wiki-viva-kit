// @vitest-environment jsdom

// AdminDock states (plan §6.3, §22.2): ?dock=admin without a session shows
// locked/unavailable, an old operator is reported as outdated, and the whole
// surface is read-only — there is no control that could mutate anything.

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SnapshotBundle } from "../types";
import type {
  AdminAccess,
  AdminCatalogResult,
  AdminPlanResult
} from "../data/admin";
import { configureLanguage, t } from "../data/i18n";
import { setAdminCommandIntent } from "../application/adminCommandIntent";

const { loadAdminAccess, fetchAdminCommandCatalog, planAdminCommand } = vi.hoisted(() => ({
  loadAdminAccess: vi.fn(async (): Promise<AdminAccess> => ({ kind: "unavailable", reason: "operator_unreachable" })),
  fetchAdminCommandCatalog: vi.fn(
    async (): Promise<AdminCatalogResult> => ({ ok: true, commands: [] })
  ),
  planAdminCommand: vi.fn(
    async (): Promise<AdminPlanResult> => ({ ok: false, errorCode: "operator_unreachable" })
  )
}));

import { AdminDock } from "./AdminDock";
import type { AdminPort } from "../application/ports";

// The dock takes its transport as an injected port (composition root); the
// tests hand it this fake — no module mocking, no network anywhere.
function adminPort(): AdminPort {
  return {
    loadAdminAccess,
    fetchAdminCommandCatalog,
    planAdminCommand,
    requestAdminChallenge: vi.fn(async () => ({ ok: false as const, errorCode: "operator_unreachable" as const })),
    unlockAdminSession: vi.fn(async () => ({ ok: false as const, errorCode: "operator_unreachable" as const })),
    renewAdminSession: vi.fn(async () => ({ ok: false as const, errorCode: "operator_unreachable" as const })),
    lockAdminSession: vi.fn(async () => ({ ok: true as const })),
    executeAdminPlan: vi.fn(async () => ({ ok: false as const, errorCode: "operator_unreachable" as const }))
  };
}

function bundle(): SnapshotBundle {
  return {
    manifest: {
      schema_version: "wiki_web_snapshot.v2",
      snapshot_id: "snap-test-1",
      generated_at: "2026-07-17T10:00:00Z",
      mode: "local_operator",
      source_commit: null,
      repo: {
        repo_id: "kit-test",
        language: "en",
        memory_root: "memories",
        default_context: "system",
        karma_enabled: true,
        default_branch: "main",
        branch_prefix: "wiki/"
      },
      files: []
    },
    git: {
      available: true,
      default_branch: "main",
      current_branch: "wiki/topic",
      branch_prefix: "wiki/",
      worktree: { clean: true, changed_files: [] },
      upstream: { remote: "", ahead: 0, behind: 0, name: "", last_fetch_at: null },
      proposal: { is_proposal_branch: true, theme: "topic", draft_pr_url: null, human_gate_state: "" }
    }
  } as unknown as SnapshotBundle;
}

function lockedAccess(): AdminAccess {
  return {
    kind: "capabilities",
    payload: {
      schema_version: "wiki_admin_capabilities.v1",
      server_version: "wiki_admin.v1",
      adapter: "local_startup_code",
      session_state: "locked",
      session: null,
      read_only: true,
      capabilities: [
        { id: "system.inspect", granted: false, reason: "session_not_authorized" },
        { id: "config.inspect", granted: false, reason: "session_not_authorized" },
        { id: "break_glass.local", granted: false, reason: "disabled_by_config" }
      ]
    }
  };
}

function activeAccess(): AdminAccess {
  const access = lockedAccess();
  if (access.kind === "capabilities") {
    access.payload.session_state = "active_full";
    access.payload.read_only = false;
    access.payload.session = {
      session_id: "session_1234",
      role: "admin",
      state: "active_full",
      expires_in_s: 900
    };
    for (const entry of access.payload.capabilities) {
      if (entry.id !== "break_glass.local") {
        entry.granted = true;
        entry.reason = undefined;
      }
    }
  }
  return access;
}

function catalogResult(): AdminCatalogResult {
  return {
    ok: true,
    commands: [
      {
        id: "system.inspect",
        title: "Inspect system state",
        capability: ["system.inspect"],
        riskLevel: "read",
        supportsDryRun: false,
        undoStrategy: null,
        granted: true
      },
      {
        id: "snapshot.rebuild",
        title: "Rebuild the published web snapshot",
        capability: ["snapshot.rebuild"],
        riskLevel: "derive",
        supportsDryRun: true,
        undoStrategy: "restore_previous_snapshot_revision",
        granted: false,
        reason: "role_not_authorized"
      }
    ]
  };
}

function plannedResult(): AdminPlanResult {
  return {
    ok: true,
    plan: {
      planId: "plan_ab12cd34",
      planSha: `sha256:${"a".repeat(64)}`,
      commandId: "system.inspect",
      title: "Inspect system state",
      riskLevel: "read",
      dryRun: false,
      summary: "Read-only inspection.",
      preconditions: [{ id: "branch", expected: "wiki/topic" }],
      effects: { filesRead: [".git"], filesWrite: [], externalCalls: [], snapshotInvalidated: false },
      diff: null,
      validation: { kind: "none" },
      undo: { kind: null, available: false },
      confirmation: { kind: "none", text: null }
    }
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  configureLanguage("en");
});

describe("AdminDock — §6.3 states, read-only", () => {
  it("shows LOCKED with zero granted capability chips when the URL opened it without a session (§22.2)", async () => {
    loadAdminAccess.mockResolvedValue(lockedAccess());
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.state.locked"))).toBeTruthy());
    expect(screen.getByText(t("admin.locked.note"))).toBeTruthy();
    expect(screen.getByText(t("admin.overview.capabilities", { granted: 0, total: 3 }))).toBeTruthy();
    // Every chip is text-labelled "not granted" — never a color-only signal.
    expect(screen.getAllByText(t("admin.capability.notGranted"))).toHaveLength(3);
    expect(screen.getByText("system.inspect")).toBeTruthy();
    // Locked surface: close, the unlock gate (PR3) and the read-only
    // re-check — still zero mutation affordances beyond the session door.
    const buttons = screen.getAllByRole("button").map((el) => el.getAttribute("aria-label") || el.textContent);
    expect(buttons).toHaveLength(3);
    expect(buttons).toContain(t("admin.dock.unlock"));
  });

  it("stays sealed in the demo: unavailable copy and no discovery request at all", () => {
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo runtimeMode="static_demo" onClose={() => {}} />);
    expect(screen.getByText(t("admin.state.unavailable"))).toBeTruthy();
    expect(screen.getByText(t("admin.reason.demo"))).toBeTruthy();
    expect(loadAdminAccess).not.toHaveBeenCalled();
    // No re-check affordance either — the demo never probes an operator.
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("reports an unreachable operator as unavailable, not locked", async () => {
    loadAdminAccess.mockResolvedValue({ kind: "unavailable", reason: "operator_unreachable" });
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="sample_fallback" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.state.unavailable"))).toBeTruthy());
    expect(screen.getByText(t("admin.reason.operator_unreachable"))).toBeTruthy();
  });

  it("detects the old operator honestly and shows the restart detail (§22.2)", async () => {
    loadAdminAccess.mockResolvedValue({
      kind: "unavailable",
      reason: "operator_outdated",
      detail: "the local operator is outdated; restart it"
    });
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.reason.operator_outdated"))).toBeTruthy());
    expect(screen.getByText("the local operator is outdated; restart it")).toBeTruthy();
  });

  it("renders the read-only session state when the server reports one", async () => {
    const access = lockedAccess();
    if (access.kind === "capabilities") access.payload.session_state = "active_readonly";
    loadAdminAccess.mockResolvedValue(access);
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.state.active_readonly"))).toBeTruthy());
    expect(screen.getByText(t("admin.readonly.note"))).toBeTruthy();
  });

  it("shows snapshot age, branch and version facts from the bundle", async () => {
    loadAdminAccess.mockResolvedValue(lockedAccess());
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("wiki_admin.v1")).toBeTruthy());
    expect(screen.getByText(t("admin.overview.snapshotAge", { when: "2026-07-17 10:00" }))).toBeTruthy();
    expect(screen.getByText("wiki/topic")).toBeTruthy();
    expect(screen.getByText("kit-test")).toBeTruthy();
    expect(
      screen.getByText(t("admin.system.frontendRequires", { version: "wiki_web_server.v8" }))
    ).toBeTruthy();
  });
});

describe("AdminDock — command bus section (plan §11/§14, PR4)", () => {
  it("locked dock has no commands section and never fetches the catalog", async () => {
    loadAdminAccess.mockResolvedValue(lockedAccess());
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.state.locked"))).toBeTruthy());
    expect(screen.queryByText(t("admin.section.commands"))).toBeNull();
    expect(fetchAdminCommandCatalog).not.toHaveBeenCalled();
  });

  it("active session lists the catalog with per-command grants and plans on click", async () => {
    loadAdminAccess.mockResolvedValue(activeAccess());
    fetchAdminCommandCatalog.mockResolvedValue(catalogResult());
    planAdminCommand.mockResolvedValue(plannedResult());
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("Inspect system state")).toBeTruthy());
    // The denied command renders present-but-absent, with its reason text.
    expect(screen.getByText("Rebuild the published web snapshot")).toBeTruthy();
    expect(screen.getByText(t("admin.capabilityReason.role_not_authorized"))).toBeTruthy();
    // Exactly one plannable command -> exactly one plan button.
    const buttons = screen.getAllByRole("button", { name: new RegExp(t("admin.commands.plan")) });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(planAdminCommand).toHaveBeenCalledWith("system.inspect", {}, { dryRun: false }));
    // The materialized plan opens the review dialog with the §11.3 contract.
    expect(await screen.findByText(t("admin.plan.contract"))).toBeTruthy();
  });

  it("a typed-command intent plans automatically once the catalog answers", async () => {
    loadAdminAccess.mockResolvedValue(activeAccess());
    fetchAdminCommandCatalog.mockResolvedValue(catalogResult());
    planAdminCommand.mockResolvedValue(plannedResult());
    setAdminCommandIntent("system.inspect");
    render(<AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() =>
      expect(planAdminCommand).toHaveBeenCalledWith("system.inspect", {}, { dryRun: false })
    );
    expect(await screen.findByText(t("admin.plan.contract"))).toBeTruthy();
  });

  it("an intent for a non-granted command becomes a notice, never a request", async () => {
    loadAdminAccess.mockResolvedValue(activeAccess());
    fetchAdminCommandCatalog.mockResolvedValue(catalogResult());
    const onNotice = vi.fn();
    setAdminCommandIntent("snapshot.rebuild");
    render(
      <AdminDock admin={adminPort()} bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} onNotice={onNotice} />
    );
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(t("admin.commands.notGranted")));
    expect(planAdminCommand).not.toHaveBeenCalled();
  });
});

describe("AdminDock — i18n parity", () => {
  const keys = [
    "nav.admin",
    "dock.mission.admin",
    "admin.dock.title",
    "admin.dock.readOnlyNote",
    "admin.dock.refresh",
    "admin.section.overview",
    "admin.section.system",
    "admin.state.loading",
    "admin.state.loadingBody",
    "admin.state.unavailable",
    "admin.state.locked",
    "admin.state.unlocking",
    "admin.state.active_readonly",
    "admin.state.active_partial",
    "admin.state.active_full",
    "admin.state.expiring",
    "admin.state.revoked",
    "admin.reason.demo",
    "admin.reason.operator_unreachable",
    "admin.reason.operator_outdated",
    "admin.reason.malformed_response",
    "admin.locked.note",
    "admin.readonly.note",
    "admin.overview.sessionState",
    "admin.overview.capabilities",
    "admin.overview.capabilitiesAria",
    "admin.capability.granted",
    "admin.capability.notGranted",
    "admin.capabilityReason.session_not_authorized",
    "admin.capabilityReason.disabled_by_config",
    "admin.capabilityReason.admin_disabled",
    "admin.overview.runtime",
    "admin.overview.snapshot",
    "admin.overview.snapshotAge",
    "admin.system.repo",
    "admin.system.branch",
    "admin.system.branchUnknown",
    "admin.system.worktree",
    "admin.system.worktreeClean",
    "admin.system.worktreeChanged",
    "admin.system.operator",
    "admin.system.operatorAbsent",
    "admin.system.adapter",
    "admin.system.versions",
    "admin.system.frontendRequires"
  ];

  it("resolves every admin surface key in both languages", () => {
    for (const lang of ["en", "pt"] as const) {
      configureLanguage(lang);
      for (const key of keys) {
        expect(t(key), `${lang}:${key}`).not.toBe(key);
      }
    }
  });

  it("keeps the §6.3 labels in Portuguese", () => {
    configureLanguage("pt");
    expect(t("admin.state.unavailable")).toBe("Admin indisponível");
    expect(t("admin.state.locked")).toBe("Admin bloqueado");
    expect(t("admin.state.active_readonly")).toBe("Admin — leitura");
  });
});
