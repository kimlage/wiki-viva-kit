// @vitest-environment jsdom

// AdminDock states (plan §6.3, §22.2): ?dock=admin without a session shows
// locked/unavailable, an old operator is reported as outdated, and the whole
// surface is read-only — there is no control that could mutate anything.

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SnapshotBundle } from "../types";
import type { AdminAccess } from "../data/admin";
import { configureLanguage, t } from "../data/i18n";

const { loadAdminAccess } = vi.hoisted(() => ({
  loadAdminAccess: vi.fn(async (): Promise<AdminAccess> => ({ kind: "unavailable", reason: "operator_unreachable" }))
}));

vi.mock("../data/admin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data/admin")>()),
  loadAdminAccess
}));

import { AdminDock } from "./AdminDock";

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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  configureLanguage("en");
});

describe("AdminDock — §6.3 states, read-only", () => {
  it("shows LOCKED with zero granted capability chips when the URL opened it without a session (§22.2)", async () => {
    loadAdminAccess.mockResolvedValue(lockedAccess());
    render(<AdminDock bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
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
    render(<AdminDock bundle={bundle()} demo runtimeMode="static_demo" onClose={() => {}} />);
    expect(screen.getByText(t("admin.state.unavailable"))).toBeTruthy();
    expect(screen.getByText(t("admin.reason.demo"))).toBeTruthy();
    expect(loadAdminAccess).not.toHaveBeenCalled();
    // No re-check affordance either — the demo never probes an operator.
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("reports an unreachable operator as unavailable, not locked", async () => {
    loadAdminAccess.mockResolvedValue({ kind: "unavailable", reason: "operator_unreachable" });
    render(<AdminDock bundle={bundle()} demo={false} runtimeMode="sample_fallback" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.state.unavailable"))).toBeTruthy());
    expect(screen.getByText(t("admin.reason.operator_unreachable"))).toBeTruthy();
  });

  it("detects the old operator honestly and shows the restart detail (§22.2)", async () => {
    loadAdminAccess.mockResolvedValue({
      kind: "unavailable",
      reason: "operator_outdated",
      detail: "the local operator is outdated; restart it"
    });
    render(<AdminDock bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.reason.operator_outdated"))).toBeTruthy());
    expect(screen.getByText("the local operator is outdated; restart it")).toBeTruthy();
  });

  it("renders the read-only session state when the server reports one", async () => {
    const access = lockedAccess();
    if (access.kind === "capabilities") access.payload.session_state = "active_readonly";
    loadAdminAccess.mockResolvedValue(access);
    render(<AdminDock bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(t("admin.state.active_readonly"))).toBeTruthy());
    expect(screen.getByText(t("admin.readonly.note"))).toBeTruthy();
  });

  it("shows snapshot age, branch and version facts from the bundle", async () => {
    loadAdminAccess.mockResolvedValue(lockedAccess());
    render(<AdminDock bundle={bundle()} demo={false} runtimeMode="local_operator" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("wiki_admin.v1")).toBeTruthy());
    expect(screen.getByText(t("admin.overview.snapshotAge", { when: "2026-07-17 10:00" }))).toBeTruthy();
    expect(screen.getByText("wiki/topic")).toBeTruthy();
    expect(screen.getByText("kit-test")).toBeTruthy();
    expect(
      screen.getByText(t("admin.system.frontendRequires", { version: "wiki_web_server.v7" }))
    ).toBeTruthy();
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
