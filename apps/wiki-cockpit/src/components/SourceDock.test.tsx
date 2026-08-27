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
import type { BriefSpec, SnapshotBundle, SourceEntity, SourceOperationPreview, SourceOperationReceipt } from "../types";
import { SourceDock } from "./SourceDock";
import { SourceWorkspace } from "./SourceWorkspace";

function sourceFixture(overrides: Partial<SourceEntity> = {}): SourceEntity {
  return {
    source_id: "source-gmail",
    path: "memories/documentos/source-gmail.md",
    title: "Gmail da equipe",
    context: "documentos",
    platform: "gmail",
    locator: "operator@example.com",
    source_kind: "account",
    owner: "Operador",
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
  it("expands the registry while keeping a readable visual name and semantic platform icon", () => {
    render(
      <SourceWorkspace
        bundle={bundleWith(sourceFixture({ title: "Fonte - Gmail da equipe" }))}
        sourceId="source-gmail"
        onNotice={noop}
        onClose={noop}
      />
    );
    const registry = screen.getByRole("complementary", { name: "Sources (1)" });
    expect(within(registry).getByText("Gmail da equipe").getAttribute("title")).toBe("Fonte - Gmail da equipe");
    expect(registry.querySelector(".lucide-mail")).toBeTruthy();
    const expand = within(registry).getByRole("button", { name: "Expand source list" });
    expect(expand.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(expand);
    expect(expand.getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector(".sourceWorkspaceBody")?.classList.contains("registryExpanded")).toBe(true);
  });

  it("keeps record selection, update, configuration and history as explicit source-only tabs", () => {
    render(<SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onNotice={noop} onClose={noop} />);
    expect(screen.getByRole("button", { name: "Records" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Update" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Configure" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "History" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Selected record details" })).toBeTruthy();
  });

  it("distinguishes covered and intentionally excluded records from never-ingested data", () => {
    const source = sourceFixture();
    source.streams.push(
      {
        id: "covered-audio",
        label: "Audio covered by transcript",
        selected: false,
        privacy: "private_self",
        target_pages: [],
        skip_reason: "Covered by the transcript source",
        cursor_age_days: null,
        cadence_days: 0,
        breached: false,
        filters: { processing_state: "covered" }
      },
      {
        id: "test-audio",
        label: "Recorder test",
        selected: false,
        privacy: "private_self",
        target_pages: [],
        skip_reason: "Short test without operational content",
        cursor_age_days: null,
        cadence_days: 0,
        breached: false,
        filters: { processing_state: "no_ingest" }
      }
    );
    render(<SourceDock bundle={bundleWith(source)} sourceId="source-gmail" onNotice={noop} onClose={noop} />);

    expect(screen.getByText("Active 2 · Covered 1 · Excluded 1")).toBeTruthy();
    expect(screen.getAllByText("covered by another source").length).toBeGreaterThan(0);
    expect(screen.getAllByText("excluded from ingestion").length).toBeGreaterThan(0);
    expect(screen.queryByText("not ingested")).toBeNull();
  });

  it("does not present elapsed time as staleness for a completed one-shot source", () => {
    const source = sourceFixture({
      source_kind: "item",
      schedule: { mode: "one_shot", cadence_days: 0, cron_hint: "" },
      next_due_days: null
    });
    source.streams[0].cursor_age_days = 79;
    render(<SourceDock bundle={bundleWith(source)} sourceId="source-gmail" onNotice={noop} onClose={noop} />);

    expect(screen.getAllByText("capture complete / One-time capture").length).toBeGreaterThan(0);
    expect(screen.queryByText("79d ago / One-time capture")).toBeNull();
  });

  it("labels a lifecycle reconstructed from proven legacy ingestion evidence", () => {
    const source = sourceFixture();
    source.lifecycle = { ...source.lifecycle!, derived_from_legacy: true };
    render(<SourceDock bundle={bundleWith(source)} sourceId="source-gmail" onNotice={noop} onClose={noop} />);
    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(screen.getByText(/Reconstructed from the versioned legacy ingestion evidence/)).toBeTruthy();
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
    fireEvent.click(screen.getByRole("button", { name: "Check connector and plan" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Check connector and plan" }));
    await waitFor(() => expect(screen.getByText(/google_drive\.list_folder is not available in Codex/)).toBeTruthy());
    const prepare = screen.getByRole("button", { name: "Prepare monitored update" }) as HTMLButtonElement;
    expect(prepare.disabled).toBe(true);
    fireEvent.click(prepare);
    expect(onComposeBrief).not.toHaveBeenCalled();
  });

  it("requires a RAW path only for a script route and hides irrelevant agent controls", async () => {
    const previewRefresh = vi.fn(async (): Promise<SourceOperationPreview> => ({
      ok: true,
      preview_token: "f".repeat(64),
      execution: { mode: "script", argv: ["python3", "scripts/ingest.py"], mcp_hint: "", how_to_export: "", runnable: true },
      steps: []
    }));
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture({ update_route: { mode: "script", mcp_hint: "", runnable: true, requires_agent: false } }))}
        sourceId="source-gmail"
        onPreviewRefresh={previewRefresh}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    const inspect = screen.getByRole("button", { name: "Check RAW and plan" }) as HTMLButtonElement;
    expect(inspect.disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Claude" })).toBeNull();
    fireEvent.change(screen.getByLabelText(/Local RAW snapshot path/), { target: { value: "data/raw/inbox.mbox" } });
    expect(inspect.disabled).toBe(false);
    fireEvent.click(inspect);
    await waitFor(() => expect(previewRefresh).toHaveBeenCalledWith("source-gmail", "__source__", "data/raw/inbox.mbox"));
  });

  it("offers direct live inventory without a fake RAW input for a deterministic connector", async () => {
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture({ update_route: { mode: "deterministic_connector", mcp_hint: "", runnable: true, requires_agent: false } }))}
        sourceId="source-gmail"
        onPreviewRefresh={vi.fn(async (): Promise<SourceOperationPreview> => ({
          ok: true,
          preview_token: "g".repeat(64),
          execution: { mode: "deterministic_connector", argv: ["python3", "scripts/inventory.py"], mcp_hint: "", how_to_export: "", runnable: true },
          steps: []
        }))}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    expect(screen.getByRole("button", { name: "Inventory live source" })).toBeTruthy();
    expect(screen.queryByLabelText(/Local RAW snapshot path/)).toBeNull();
  });

  it("shows a deterministic collection diff and applies only selected records", async () => {
    const onRunRefresh = vi.fn(async (): Promise<SourceOperationReceipt> => ({
      ok: true,
      operation_id: "sop-inventory",
      recorded_at: "2026-08-27T12:00:00Z",
      source_id: "source-gmail",
      stream_id: "__source__",
      status: "inventory_applied",
      changes: [{ field: "record:new-1", before: null, after: { id: "new-1" } }]
    }));
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture())}
        sourceId="source-gmail"
        onPreviewRefresh={vi.fn(async (): Promise<SourceOperationPreview> => ({
          ok: true,
          preview_token: "d".repeat(64),
          execution: { mode: "deterministic_connector", argv: ["python3", "scripts/inventory.py"], mcp_hint: "", how_to_export: "", runnable: true },
          discovery: {
            counts: { new: 1, changed: 1, enriched: 0, unchanged: 3 },
            fingerprint: "e".repeat(64),
            records: [
              { external_id: "new-1", label: "New recording", filters: { size_bytes: 42 }, status: "new" },
              { external_id: "changed-1", label: "Changed recording", filters: { size_bytes: 84 }, status: "changed", stream_id: "inbox" }
            ]
          },
          steps: []
        }))}
        onRunRefresh={onRunRefresh}
        onNotice={noop}
        onClose={noop}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    fireEvent.click(screen.getByRole("button", { name: "Check connector and plan" }));
    await waitFor(() => expect(screen.getByText("Live collection comparison")).toBeTruthy());
    expect(screen.getByText("1 new")).toBeTruthy();
    expect(screen.getByText("1 changed")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /Changed recording/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add selected records" }));
    await waitFor(() => expect(onRunRefresh).toHaveBeenCalledWith(
      "source-gmail",
      "__source__",
      "",
      "d".repeat(64),
      ["new-1"]
    ));
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

  it("previews source type and lifecycle changes at source scope", async () => {
    const previewConfiguration = vi.fn(async () => ({
      ok: true,
      preview_token: "d".repeat(64),
      config_ref: "memories/documentos/config-gmail.md",
      updates: { schedule_mode: "on_demand", schedule_cadence_days: 0 },
      changes: [{ field: "schedule_mode", before: "recurring", after: "on_demand" }],
      steps: []
    }));
    render(<SourceDock bundle={bundleWith(sourceFixture())} sourceId="source-gmail" onPreviewConfiguration={previewConfiguration} onNotice={noop} onClose={noop} />);
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    fireEvent.change(screen.getByLabelText("Update lifecycle"), { target: { value: "on_demand" } });
    expect((screen.getByLabelText(/^Cadence \(days\)/) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Review source settings" }));
    await waitFor(() => expect(previewConfiguration).toHaveBeenCalledWith(
      "source-gmail",
      "__source__",
      expect.objectContaining({ schedule_mode: "on_demand", schedule_cadence_days: 0 })
    ));
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
      expect((screen.getByLabelText("Record cadence (days)") as HTMLInputElement).value).toBe("14");
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
  it("removes redundant source prefixes from the visual name without changing the canonical title", () => {
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture({ title: "Fonte - Gmail da equipe" }))}
        sourceId="source-gmail"
        onNotice={noop}
        onClose={noop}
      />
    );
    expect(screen.getByText("Gmail da equipe").getAttribute("title")).toBe("Fonte - Gmail da equipe");
    expect(screen.queryByText("Fonte - Gmail da equipe")).toBeNull();
    expect(document.querySelector(".dockHeader .lucide-mail")).toBeTruthy();
  });

  it("shows authorization readiness before an update is attempted", () => {
    render(
      <SourceDock
        bundle={bundleWith(sourceFixture({
          update_route: { mode: "agent_connector", mcp_hint: "google-drive", runnable: false, requires_agent: true }
        }))}
        sourceId="source-gmail"
        agentCapabilities={{
          codex: { enabled: true, installed: true, runnable: true, authed: true, auth_mode: "chatgpt", version: "1", usable: true, reason: "", connectors: [] },
          claude: { enabled: true, installed: true, runnable: true, authed: true, auth_mode: "claude.ai", version: "1", usable: true, reason: "", connectors: ["blender"] }
        }}
        onNotice={noop}
        onClose={noop}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Update" }));
    const authorization = screen.getByRole("region", { name: "Authorization and live access" });
    expect(within(authorization).getByText("Connector unavailable")).toBeTruthy();
    expect(within(authorization).getByText("keychain:gmail-personal")).toBeTruthy();
    expect(within(authorization).getByText(/does not expose google-drive/)).toBeTruthy();
  });

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
