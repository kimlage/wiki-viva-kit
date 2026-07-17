// @vitest-environment jsdom

// SourceDock interaction + lifecycle parity (§12.3, §12.6, §13.1, §14.4,
// §19.6): the dock shows the server-authoritative lifecycle projection, the
// ephemeral focusedStreamId focuses the exact stream row (recipe id — never a
// derived id, never a URL), trace toggles are selection-driven callbacks, the
// brief stays server-composed, the auth block is a pointer without any secret
// value, and focus returns to the opener after the dock closes.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import type { BriefSpec, SnapshotBundle, SourceEntity } from "../types";
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
    await vi.waitFor(() => expect(compose).toHaveBeenCalledWith(serverSpec));
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
