// @vitest-environment jsdom

// SourceDock interaction + lifecycle parity (§12.3, §12.6, §13.1, §14.4,
// §19.6): the dock shows the server-authoritative lifecycle projection, the
// ephemeral focusedStreamId focuses the exact stream row (recipe id — never a
// derived id, never a URL), trace toggles are selection-driven callbacks, the
// brief stays server-composed, the auth block is a pointer without any secret
// value, and focus returns to the opener after the dock closes.

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import type { BriefSpec, SnapshotBundle, SourceEntity, SourceOperationPreview } from "../types";
import { SourceDock } from "./SourceDock";

function sourceFixture(overrides: Partial<SourceEntity> = {}): SourceEntity {
  return {
    source_id: "source-gmail",
    path: "memories/documentos/source-gmail.md",
    title: "Gmail pessoal",
    context: "documentos",
    platform: "gmail",
    locator: "kim@example.com",
    owner: "Kim",
    stewards: [],
    config_ref: "memories/documentos/config-gmail.md",
    updated_at: "2026-07-01",
    sync: {
      last_run_at: "2026-07-10T08:00:00Z",
      last_status: "ok",
      last_event_ref: "event-ingest-gmail-2026-07",
      streams_fresh: 1,
      streams_total: 2,
      event_closure: {
        consolidated_into: ["nota-consolidada"],
        reviewed_no_change: true,
        no_change: [],
        gate_state: "pending"
      }
    },
    lifecycle: {
      state: "consolidated",
      freshness_state: "fresh",
      last_attempt_state: "success",
      pipeline_stage: "gate_pending",
      pipeline_stage_timestamps: {},
      adoption_state: "adopted",
      last_sync_success_at: "2026-07-10T08:00:00Z",
      last_ingested_at: "2026-07-10T08:00:00Z",
      last_attempt_at: "2026-07-10T08:00:00Z",
      emitted_page_ids: ["nota-a", "nota-b", "nota-c", "nota-d", "nota-e", "nota-f", "nota-g"],
      emitted_action_ids: ["acao-1"],
      proposal_ids: ["proposta-1"],
      raw_artifact_count: 3,
      secret_safe_log_refs: [],
      reviewed_no_change_receipt: "",
      accepted_ref: "memories/documentos/nota-a.md",
      blocked_reason: "",
      authoring_error_codes: ["source_lifecycle_missing_field"]
    },
    recipe_ok: true,
    recipe_errors: [],
    how_to_export: "Export the mailbox as mbox.",
    pipelines: [{ kind: "content", cadence_days: 7 }],
    streams: [
      {
        id: "inbox",
        label: "Inbox operacional",
        selected: true,
        privacy: "private_self",
        target_pages: ["nota-a"],
        skip_reason: "",
        cursor_age_days: 2,
        cadence_days: 7,
        breached: false
      },
      {
        id: "sent",
        label: "Enviadas",
        selected: true,
        privacy: "private_self",
        target_pages: [],
        skip_reason: "",
        cursor_age_days: 12,
        cadence_days: 7,
        breached: true
      }
    ],
    pending_streams: 1,
    auth: { method: "oauth", ref: "keychain:gmail-personal", scopes: ["read"], note: "" },
    schedule: { mode: "recurring", cadence_days: 7, cron_hint: "" },
    next_due_days: 2,
    ...overrides
  };
}

function bundleWith(source: SourceEntity | null): SnapshotBundle {
  return {
    sourceEntities: {
      schema_version: "wiki_web_source_entities.v1",
      sources: source ? [source] : []
    }
  } as unknown as SnapshotBundle;
}

const noop = () => undefined;

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("SourceDock operational workspace", () => {
  it("keeps record selection, update, configuration and history as explicit source-only tabs", () => {
    render(<SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onNotice={noop} onClose={noop} />);
    expect(screen.getByRole("button", { name: "Records" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Update" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Configure" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "History" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Selected record details" })).toBeTruthy();
  });

  it("carries the chosen Claude adapter into the exact source brief", async () => {
    const onComposeBrief = vi.fn();
    const spec: BriefSpec = { grounding: { page_ids: [] }, intent: "refresh source" };
    const previewRefresh = vi.fn(async (): Promise<SourceOperationPreview> => ({
      ok: true,
      preview_token: "b".repeat(64),
      execution: { mode: "agent_connector", argv: [], mcp_hint: "google-drive", how_to_export: "List metadata", requires_agent: true },
      steps: []
    }));
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onRequestBrief={vi.fn(async () => ({ ok: true, spec }))}
        onPreviewRefresh={previewRefresh}
        onComposeBrief={onComposeBrief}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    fireEvent.click(screen.getByRole("button", { name: "Claude" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Validate update route" })[0]);
    await waitFor(() => expect(screen.getByText("Verified execution plan")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Prepare monitored update" }));
    await waitFor(() => expect(onComposeBrief).toHaveBeenCalledWith({ ...spec, agent: "claude" }));
  });

  it("blocks delegation when the selected agent does not expose the declared connector", async () => {
    const onComposeBrief = vi.fn();
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        agentCapabilities={{
          codex: { enabled: true, installed: true, runnable: true, authed: true, auth_mode: "chatgpt", version: "1", usable: true, reason: "", connectors: [] },
          claude: { enabled: true, installed: true, runnable: true, authed: true, auth_mode: "claude.ai", version: "1", usable: true, reason: "", connectors: ["blender"] }
        }}
        onRequestBrief={vi.fn(async () => ({ ok: true, spec: { grounding: {} } }))}
        onPreviewRefresh={vi.fn(async (): Promise<SourceOperationPreview> => ({
          ok: true,
          preview_token: "c".repeat(64),
          execution: { mode: "agent_connector", argv: [], mcp_hint: "google_drive.list_folder", how_to_export: "List metadata", requires_agent: true },
          steps: []
        }))}
        onComposeBrief={onComposeBrief}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Validate update route" })[0]);
    await waitFor(() => expect(screen.getByText(/google_drive\.list_folder is not available in Codex/)).toBeTruthy());
    const prepare = screen.getByRole("button", { name: "Prepare monitored update" }) as HTMLButtonElement;
    expect(prepare.disabled).toBe(true);
    fireEvent.click(prepare);
    expect(onComposeBrief).not.toHaveBeenCalled();
  });

  it("previews a typed record change before exposing the confirm action", async () => {
    const previewConfiguration = vi.fn(async () => ({
      ok: true,
      preview_token: "a".repeat(64),
      config_ref: "memories/documentos/config-gmail.md",
      updates: { label: "Inbox revisada" },
      changes: [{ field: "label", before: "Inbox operacional", after: "Inbox revisada" }],
      steps: [
        { id: "bind", label: "Confirm source and selected record", status: "complete" },
        { id: "write", label: "Write only after explicit confirmation", status: "pending" }
      ]
    }));
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onPreviewConfiguration={previewConfiguration}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    const label = screen.getByLabelText("Display label");
    fireEvent.change(label, { target: { value: "Inbox revisada" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate safe preview" }));
    await waitFor(() => expect(screen.getByText("Review before applying")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Confirm and apply" })).toBeTruthy();
    expect(previewConfiguration).toHaveBeenCalledWith(
      "source-gmail",
      "inbox",
      expect.objectContaining({ label: "Inbox revisada" })
    );
  });

  it("refreshes the configuration draft when the authoritative source record changes", async () => {
    const { rerender } = render(
      <SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onNotice={noop} onClose={noop} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    expect((screen.getByLabelText("Display label") as HTMLInputElement).value).toBe("Inbox operacional");

    const refreshed = sourceFixture();
    refreshed.streams[0] = {
      ...refreshed.streams[0],
      label: "Inbox consolidada",
      cadence_days: 14,
      filters: { processing_state: "reviewed" }
    };
    rerender(
      <SourceDock bundle={bundleWith(refreshed)} sourceId="source-gmail" onNotice={noop} onClose={noop} />
    );

    await waitFor(() => {
      expect((screen.getByLabelText("Display label") as HTMLInputElement).value).toBe("Inbox consolidada");
      expect((screen.getByLabelText("Cadence (days)") as HTMLInputElement).value).toBe("14");
      expect((screen.getByLabelText("Processing state") as HTMLInputElement).value).toBe("reviewed");
    });
  });
});

describe("SourceDock lifecycle parity (§13.1)", () => {
  it("shows lifecycle state, stage, adoption, last attempt, accepted ref, emissions, closure and safe codes", () => {
    configureLanguage("en");
    const openPage = vi.fn();
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onNotice={noop}
        onOpenPage={openPage}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(screen.getByText("Lifecycle")).toBeTruthy();
    expect(screen.getByText("consolidated")).toBeTruthy();
    expect(screen.getByText("gate_pending")).toBeTruthy();
    expect(screen.getByText("adopted")).toBeTruthy();
    expect(screen.getByText("success")).toBeTruthy();
    // Emitted census is honest counts from the projection.
    expect(screen.getByText("Emitted: 7 page(s) · 1 action(s) · 1 proposal(s)")).toBeTruthy();
    // Emitted page links are capped with an honest remainder.
    expect(screen.getByText("+2 more")).toBeTruthy();
    // Closure summary of the newest event.
    expect(screen.getByText(/gate pending/)).toBeTruthy();
    expect(screen.getByText(/consolidated into 1 page/)).toBeTruthy();
    expect(screen.getByText(/review found no change/)).toBeTruthy();
    // Safe diagnostic codes render as codes.
    expect(screen.getByText("source_lifecycle_missing_field")).toBeTruthy();
    // The accepted ref opens the REAL page through the same reader callback.
    fireEvent.click(screen.getByRole("button", { name: "memories/documentos/nota-a.md" }));
    expect(openPage).toHaveBeenCalledWith("memories/documentos/nota-a.md");
  });

  it("renders the lifecycle section in Portuguese with the same data", () => {
    configureLanguage("pt-BR");
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Histórico" }));
    expect(screen.getByText("Ciclo de vida")).toBeTruthy();
    expect(screen.getByText("Emitido: 7 página(s) · 1 ação(ões) · 1 proposta(s)")).toBeTruthy();
    expect(screen.getByText(/revisão sem mudança/)).toBeTruthy();
  });

  it("stays silent for older snapshots without a lifecycle projection", () => {
    const source = sourceFixture();
    delete (source as { lifecycle?: unknown }).lifecycle;
    delete (source.sync as { event_closure?: unknown }).event_closure;
    render(
      <SourceDock bundle={bundleWith(source)} sourceId="source-gmail" onNotice={noop} onClose={noop} />
    );
    expect(screen.queryByText("Lifecycle")).toBeNull();
  });
});

describe("SourceDock stream focus (§12.3/§19.6)", () => {
  it("focuses the exact stream row named by the ephemeral recipe id and announces its facts", () => {
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        focusedStreamId="sent"
        onNotice={noop}
        onClose={noop}
      />
    );
    const row = document.querySelector('tr[data-stream-id="sent"]') as HTMLTableRowElement;
    expect(row).toBeTruthy();
    expect(document.activeElement).toBe(row);
    expect(row.className).toContain("streamFocused");
    // The row's accessible name carries freshness, cadence and privacy.
    const aria = row.getAttribute("aria-label") ?? "";
    expect(aria).toContain("sent");
    expect(aria).toContain("12d ago");
    expect(aria).toContain("every 7d");
    expect(aria).toContain("private_self");
    // The other row is untouched.
    const other = document.querySelector('tr[data-stream-id="inbox"]') as HTMLTableRowElement;
    expect(other.className).not.toContain("streamFocused");
  });

  it("keeps the dock DOM free of duplicate element ids", () => {
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        focusedStreamId="inbox"
        onNotice={noop}
        onOpenPage={noop}
        onClose={noop}
      />
    );
    const ids = [...document.querySelectorAll("[id]")].map((element) => element.id).filter(Boolean);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("SourceDock record selection", () => {
  it("selects a record and exposes deterministic metadata plus target links", () => {
    const source = sourceFixture();
    source.streams[0].filters = {
      file_id: "drive-file-123",
      mime_type: "audio/m4a",
      size_bytes: 1048576,
      created_at: "2026-07-01T10:00:00Z",
      processing_state: "ingested"
    };
    const openPage = vi.fn();
    render(
      <SourceDock
        bundle={bundleWith(source)}
        sourceId="source-gmail"
        onNotice={noop}
        onOpenPage={openPage}
        onClose={noop}
      />
    );

    const detail = screen.getByRole("region", { name: "Selected record details" });
    expect(within(detail).getByText("drive-file-123")).toBeTruthy();
    expect(within(detail).getByText("1.00 MB")).toBeTruthy();
    fireEvent.click(within(detail).getByRole("button", { name: "nota-a" }));
    expect(openPage).toHaveBeenCalledWith("nota-a");

    fireEvent.click(document.querySelector('tr[data-stream-id="sent"]') as HTMLTableRowElement);
    expect(within(detail).getByText("Enviadas")).toBeTruthy();
    expect(within(detail).queryByText("drive-file-123")).toBeNull();
  });
});

describe("SourceDock trace selection (§12.6/§13.2)", () => {
  it("toggles each trace mode through onHighlightTrace and clears on re-press", () => {
    const highlight = vi.fn();
    const { rerender } = render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        traceMode={null}
        onHighlightTrace={highlight}
        onNotice={noop}
        onClose={noop}
      />
    );
    const downstream = screen.getByRole("button", { name: "Downstream" });
    expect(downstream.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(downstream);
    expect(highlight).toHaveBeenLastCalledWith("downstream");
    rerender(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        traceMode="downstream"
        onHighlightTrace={highlight}
        onNotice={noop}
        onClose={noop}
      />
    );
    const pressed = screen.getByRole("button", { name: "Downstream" });
    expect(pressed.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(pressed);
    expect(highlight).toHaveBeenLastCalledWith(null);
    fireEvent.click(screen.getByRole("button", { name: "Upstream" }));
    expect(highlight).toHaveBeenLastCalledWith("upstream");
    fireEvent.click(screen.getByRole("button", { name: "Closure" }));
    expect(highlight).toHaveBeenLastCalledWith("closure");
  });

  it("offers no trace controls without the scene callback", () => {
    render(
      <SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onNotice={noop} onClose={noop} />
    );
    expect(screen.queryByRole("button", { name: "Downstream" })).toBeNull();
  });
});

describe("SourceDock brief flow (§19.6)", () => {
  it("keeps the brief server-authoritative: the composed spec comes from onRequestBrief", async () => {
    const serverSpec = { mission_kind: "ingest", theme: "sync-gmail" } as unknown as BriefSpec;
    const requestBrief = vi.fn().mockResolvedValue({ ok: true, spec: serverSpec });
    const compose = vi.fn();
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onComposeBrief={compose}
        onRequestBrief={requestBrief}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Sync with Codex/ }));
    await vi.waitFor(() => expect(compose).toHaveBeenCalledWith({ ...serverSpec, agent: "codex" }));
    expect(requestBrief).toHaveBeenCalledWith("source-gmail");
  });

  it("reports an honest failure when the server cannot compose", async () => {
    const requestBrief = vi.fn().mockResolvedValue({ ok: false, error: "recipe missing" });
    const notice = vi.fn();
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onComposeBrief={vi.fn()}
        onRequestBrief={requestBrief}
        onNotice={notice}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /Sync with Codex/ }));
    await vi.waitFor(() => expect(notice).toHaveBeenCalled());
    expect(String(notice.mock.calls[0][0])).toContain("recipe missing");
  });
});

describe("SourceDock honest edges (§19.6)", () => {
  it("says when a source is not in the snapshot", () => {
    render(<SourceDock bundle={bundleWith(null)} sourceId="ghost" onNotice={noop} onClose={noop} />);
    expect(screen.getByText("Source `ghost` is not in this snapshot.")).toBeTruthy();
  });

  it("surfaces invalid recipe errors verbatim", () => {
    const source = sourceFixture({ recipe_ok: false, recipe_errors: ["platform: unknown value"] });
    render(<SourceDock bundle={bundleWith(source)} sourceId="source-gmail" onNotice={noop} onClose={noop} />);
    expect(screen.getByText("Recipe has problems")).toBeTruthy();
    expect(screen.getByText(/platform: unknown value/)).toBeTruthy();
  });

  it("shows the auth pointer without ever holding a secret value", () => {
    render(
      <SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onNotice={noop} onClose={noop} />
    );
    expect(screen.getByText("Auth via oauth")).toBeTruthy();
    expect(screen.getByText("keychain:gmail-personal")).toBeTruthy();
    // Pointer only: no input holds a credential and no password field exists.
    expect(document.querySelector("input")).toBeNull();
  });
});

describe("SourceDock focus restore (§14.4/§19.6)", () => {
  it("returns focus to the opener when the dock closes and nothing else claimed it", () => {
    const opener = document.createElement("button");
    opener.textContent = "port twin";
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        focusedStreamId="inbox"
        onNotice={noop}
        onClose={noop}
      />
    );
    // The dock claimed focus for the stream row while open.
    expect(document.activeElement?.getAttribute("data-stream-id")).toBe("inbox");
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("never steals focus back when another surface already claimed it", () => {
    const opener = document.createElement("button");
    const other = document.createElement("button");
    document.body.append(opener, other);
    opener.focus();
    const { unmount } = render(
      <SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onNotice={noop} onClose={noop} />
    );
    other.focus();
    unmount();
    expect(document.activeElement).toBe(other);
    opener.remove();
    other.remove();
  });
});
