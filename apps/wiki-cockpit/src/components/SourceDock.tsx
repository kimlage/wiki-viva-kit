// SourceDock (?dock=source&src=<id>): a data source as a FIRST-CLASS entity.
// Identity (platform · locator · owner), sync health, the channels/streams as a
// table with per-stream freshness vs cadence, the executable export manual, and
// the actions: compose an ingestion brief for the stale streams (recipe becomes
// the grounding), open the config. The source page's machine sync block and the
// human recipe stay clearly separated. Everything t()'d EN+PT.

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  Database,
  ExternalLink,
  File,
  History,
  Loader2,
  Lock,
  Pencil,
  Play,
  Radio,
  RefreshCw,
  Save,
  Settings2,
  X
} from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel } from "../data/presentation";
import { DockTelemetryRail, type DockTelemetryItem } from "./DockTelemetryRail";
import { ExpandablePre } from "./ExpandablePre";
import type { AgentCapabilities, BriefSpec, SnapshotBundle, SourceEntity, SourceOperationPreview, SourceOperationReceipt } from "../types";

type SourceSection = "records" | "update" | "configure" | "history";
type SourceTraceMode = "upstream" | "downstream" | "closure";
type StreamDraft = {
  label: string;
  selected: boolean;
  privacy: string;
  cadenceDays: string;
  processingState: string;
  skipReason: string;
  targetPages: string;
};

const EMPTY_DRAFT: StreamDraft = {
  label: "",
  selected: true,
  privacy: "private_self",
  cadenceDays: "0",
  processingState: "",
  skipReason: "",
  targetPages: ""
};

const TRACE_MODES: SourceTraceMode[] = ["upstream", "downstream", "closure"];
const EMITTED_PAGE_LINK_BUDGET = 5;

function formatWhen(when: string): string {
  return when.replace("T", " ").slice(0, 16);
}

const SYNC_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  ok: "good",
  partial: "warn",
  running: "muted",
  queued: "muted",
  failed: "bad",
  never: "muted"
};

function ageLabel(days: number | null): string {
  if (days === null) return t("source.stream.never");
  if (days <= 0) return t("source.stream.today");
  return t("source.stream.daysAgo", { n: days });
}

function formatBytes(value: unknown): string {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return String(value ?? "");
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}
function sourceTelemetry(sources: SourceEntity[]): DockTelemetryItem[] {
  const totalStreams = sources.reduce((sum, source) => sum + source.sync.streams_total, 0);
  const freshStreams = sources.reduce((sum, source) => sum + source.sync.streams_fresh, 0);
  const pending = sources.reduce((sum, source) => sum + source.pending_streams, 0);
  const brokenRecipes = sources.filter((source) => !source.recipe_ok).length;
  return [
    {
      key: "sources",
      label: t("source.telemetry.sources"),
      value: sources.length,
      tone: "info",
      ratio: sources.length > 0 ? 1 : 0,
      detail: t("source.list.title", { n: sources.length })
    },
    {
      key: "fresh",
      label: t("source.telemetry.fresh"),
      value: `${freshStreams}/${totalStreams}`,
      tone: totalStreams > 0 && freshStreams === totalStreams ? "good" : pending > 0 ? "warn" : "muted",
      ratio: totalStreams > 0 ? freshStreams / totalStreams : 0,
      detail: t("source.health.fresh", { fresh: freshStreams, total: totalStreams })
    },
    {
      key: "pending",
      label: t("source.telemetry.pending"),
      value: pending,
      tone: pending > 0 ? "warn" : "good",
      ratio: sources.length > 0 ? pending / Math.max(totalStreams, 1) : 0,
      detail: pending > 0 ? t("source.list.pending", { n: pending }) : t("source.telemetry.none")
    },
    {
      key: "recipes",
      label: t("source.telemetry.recipes"),
      value: brokenRecipes,
      tone: brokenRecipes > 0 ? "bad" : "good",
      ratio: sources.length > 0 ? 1 - brokenRecipes / sources.length : 0,
      detail: brokenRecipes > 0 ? t("source.telemetry.recipesBroken", { n: brokenRecipes }) : t("source.telemetry.recipesOk")
    }
  ];
}

export function SourceDock({
  bundle,
  sourceId,
  demo = false,
  focusedStreamId = null,
  traceMode = null,
  onHighlightTrace,
  onComposeBrief,
  agentCapabilities,
  onRequestBrief,
  onPreviewConfiguration,
  onApplyConfiguration,
  onListReceipts,
  onPreviewRefresh,
  onRunRefresh,
  onSourceChanged,
  onNotice,
  onOpenPage,
  onOpenSource,
  onClose
}: {
  bundle: SnapshotBundle;
  sourceId: string;
  demo?: boolean;
  // §12.3: ephemeral stream focus from a scene port activation — a RECIPE
  // stream id (never a derived id, never a URL parameter).
  focusedStreamId?: string | null;
  // §12.6/§13.2: selection-driven trace highlight over the scene.
  traceMode?: SourceTraceMode | null;
  onHighlightTrace?: (mode: SourceTraceMode | null) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  agentCapabilities?: AgentCapabilities;
  onRequestBrief?: (sourceId: string) => Promise<{ ok: boolean; spec?: BriefSpec; error?: string }>;
  onPreviewConfiguration?: (sourceId: string, streamId: string, updates: Record<string, unknown>) => Promise<SourceOperationPreview>;
  onApplyConfiguration?: (sourceId: string, streamId: string, updates: Record<string, unknown>, previewToken: string) => Promise<SourceOperationReceipt>;
  onListReceipts?: (sourceId: string, options?: { signal?: AbortSignal }) => Promise<SourceOperationReceipt[]>;
  onPreviewRefresh?: (sourceId: string, streamId: string, rawPath?: string) => Promise<SourceOperationPreview>;
  onRunRefresh?: (sourceId: string, streamId: string, rawPath: string, previewToken: string) => Promise<SourceOperationReceipt>;
  onSourceChanged?: () => void;
  onNotice: (text: string) => void;
  onOpenPage?: (pathOrId: string) => void;
  onOpenSource?: (id: string) => void;
  onClose: () => void;
}) {
  const sources = bundle.sourceEntities?.sources ?? [];
  const source: SourceEntity | undefined = useMemo(
    () => (sourceId ? sources.find((s) => s.source_id === sourceId) : undefined),
    [sources, sourceId]
  );
  const [selectedStreamId, setSelectedStreamId] = useState("");
  const [section, setSection] = useState<SourceSection>("records");
  const [draft, setDraft] = useState<StreamDraft>(EMPTY_DRAFT);
  const [operationPreview, setOperationPreview] = useState<SourceOperationPreview | null>(null);
  const [operationBusy, setOperationBusy] = useState(false);
  const [operationError, setOperationError] = useState("");
  const [receipts, setReceipts] = useState<SourceOperationReceipt[]>([]);
  const [agentPreference, setAgentPreference] = useState<"codex" | "claude">("codex");
  const [rawPath, setRawPath] = useState("");
  const [refreshPreview, setRefreshPreview] = useState<SourceOperationPreview | null>(null);
  const [refreshReceipt, setRefreshReceipt] = useState<SourceOperationReceipt | null>(null);

  useEffect(() => {
    const streams = source?.streams ?? [];
    const focused = streams.find((stream) => stream.id === focusedStreamId);
    setSelectedStreamId(focused?.id ?? streams[0]?.id ?? "");
  }, [source?.source_id, focusedStreamId]);

  const selectedForDraft = source?.streams.find((stream) => stream.id === selectedStreamId) ?? source?.streams[0];
  useEffect(() => {
    if (!selectedForDraft) {
      setDraft(EMPTY_DRAFT);
      return;
    }
    setDraft({
      label: selectedForDraft.label || selectedForDraft.id,
      selected: selectedForDraft.selected,
      privacy: selectedForDraft.privacy,
      cadenceDays: String(selectedForDraft.cadence_days ?? 0),
      processingState: String(selectedForDraft.filters?.processing_state ?? ""),
      skipReason: selectedForDraft.skip_reason ?? "",
      targetPages: selectedForDraft.target_pages.join("\n")
    });
    setOperationPreview(null);
    setOperationError("");
    setRefreshPreview(null);
    setRefreshReceipt(null);
    setRawPath("");
  }, [selectedForDraft?.id, source?.source_id]);

  useEffect(() => {
    if (!source?.source_id || demo || !onListReceipts) {
      setReceipts([]);
      return undefined;
    }
    const controller = new AbortController();
    onListReceipts(source.source_id, { signal: controller.signal })
      .then(setReceipts)
      .catch(() => setReceipts([]));
    return () => controller.abort();
  }, [source?.source_id, demo, onListReceipts]);

  // §14.4 focus restore: remember what opened the dock and give focus back on
  // close — but only when nothing else (the route-driven WorldView restore, a
  // reader) has claimed focus meanwhile. Captured once per dock lifetime.
  const dockRef = useRef<HTMLElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const opener = openerRef.current;
      if (!opener || !opener.isConnected) return;
      const active = document.activeElement;
      const unclaimed = !active || active === document.body || Boolean(dockRef.current?.contains(active));
      if (unclaimed) opener.focus({ preventScroll: true });
    };
  }, []);

  // §12.3: scroll/focus the stream row named by the ephemeral port signal.
  // The row's aria-label announces cadence/freshness/privacy on focus.
  const streamRowRefs = useRef(new Map<string, HTMLTableRowElement>());
  useEffect(() => {
    if (!focusedStreamId) return;
    const row = streamRowRefs.current.get(focusedStreamId);
    if (!row) return;
    row.focus({ preventScroll: true });
    if (typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "nearest" });
  }, [focusedStreamId, source?.source_id]);

  // LIST MODE — no specific source selected: every source, sorted by attention
  // (pending streams first), each a button that drills into its detail.
  if (!sourceId) {
    const ordered = [...sources].sort(
      (a, b) => b.pending_streams - a.pending_streams || a.title.localeCompare(b.title)
    );
    const pendingTotal = sources.reduce((sum, s) => sum + s.pending_streams, 0);
    return (
      <>
        <div className="dockBackdrop" onClick={onClose} aria-hidden />
        <aside ref={dockRef} className="sourceDock worldDock" role="dialog" aria-label={t("source.list.title")}>
          <header className="dockHeader">
            <Database size={15} aria-hidden />
            <strong>{t("source.list.title", { n: sources.length })}</strong>
            <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
              <X size={16} />
            </button>
          </header>
          <p className="dockIntro">
            {t("source.list.intro")}
            {pendingTotal > 0 ? ` ${t("source.list.pending", { n: pendingTotal })}` : ""}
          </p>
          <DockTelemetryRail label={t("source.telemetry.aria")} items={sourceTelemetry(ordered)} />
          {ordered.length === 0 && <p className="dockIntro">{t("source.list.empty")}</p>}
          <ul className="sourceList">
            {ordered.map((s) => {
              const tone = SYNC_TONE[s.sync.last_status] ?? "muted";
              return (
                <li key={s.source_id}>
                  <button className="sourceListItem" onClick={() => onOpenSource?.(s.source_id)} type="button">
                    <span className="sourceListName">
                      <strong>{s.title}</strong>
                      <small>
                        <span className="sourceBadge sourceBadgeSm">{s.platform || t("source.platform.unknown")}</span>
                        {s.locator ? ` · ${s.locator}` : ""}
                      </small>
                    </span>
                    <span className="sourceListState">
                      {s.pending_streams > 0 && <span className="pill pill-warn">{t("source.list.pendingN", { n: s.pending_streams })}</span>}
                      <span className={`pill pill-${tone}`}>{t(`source.sync.${s.sync.last_status}`)}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>
      </>
    );
  }

  if (!source) {
    return (
      <>
        <div className="dockBackdrop" onClick={onClose} aria-hidden />
        <aside ref={dockRef} className="sourceDock worldDock" role="dialog" aria-label={t("source.title")}>
          <header className="dockHeader">
            <strong>{t("source.title")}</strong>
            <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
              <X size={16} />
            </button>
          </header>
          <p className="dockIntro">{t("source.notFound", { id: sourceId })}</p>
          {onOpenSource && (
            <button className="secondaryButton" onClick={() => onOpenSource("")} type="button">
              <span>{t("source.list.back")}</span>
            </button>
          )}
        </aside>
      </>
    );
  }

  const syncTone = SYNC_TONE[source.sync.last_status] ?? "muted";
  const selected = source.streams.filter((s) => s.selected);
  const selectedStream = source.streams.find((stream) => stream.id === selectedStreamId) ?? source.streams[0];
  const activeAgentCapability = agentCapabilities?.[agentPreference];
  const connectorHint = refreshPreview?.execution?.mcp_hint ?? "";
  const connectorKey = connectorHint.split(/[./]/, 1)[0].replace(/[^a-z0-9]/gi, "").toLowerCase();
  const connectorReady = !refreshPreview?.execution?.requires_agent || !agentCapabilities || Boolean(
    activeAgentCapability?.connectors?.some(
      (name) => name.replace(/[^a-z0-9]/gi, "").toLowerCase() === connectorKey
    )
  );
  const agentReady = !agentCapabilities || Boolean(activeAgentCapability?.usable);

  const collectUpdates = (): Record<string, unknown> => {
    if (!selectedStream) return {};
    const targets = draft.targetPages
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    const values: Record<string, unknown> = {
      label: draft.label.trim(),
      selected: draft.selected,
      privacy: draft.privacy,
      cadence_days: Number(draft.cadenceDays || 0),
      processing_state: draft.processingState.trim(),
      skip_reason: draft.skipReason.trim(),
      target_pages: targets
    };
    const current: Record<string, unknown> = {
      label: selectedStream.label || selectedStream.id,
      selected: selectedStream.selected,
      privacy: selectedStream.privacy,
      cadence_days: selectedStream.cadence_days ?? 0,
      processing_state: String(selectedStream.filters?.processing_state ?? ""),
      skip_reason: selectedStream.skip_reason ?? "",
      target_pages: selectedStream.target_pages
    };
    return Object.fromEntries(
      Object.entries(values).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(current[key]))
    );
  };

  const previewConfiguration = async () => {
    if (demo || !selectedStream) return;
    setOperationBusy(true);
    setOperationError("");
    setOperationPreview(null);
    try {
      if (!onPreviewConfiguration) throw new Error(t("source.operation.unavailable"));
      const result = await onPreviewConfiguration(source.source_id, selectedStream.id, collectUpdates());
      if (!result.ok) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setOperationPreview(result);
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const confirmConfiguration = async () => {
    if (demo || !selectedStream || !operationPreview?.preview_token || !operationPreview.updates) return;
    setOperationBusy(true);
    setOperationError("");
    try {
      if (!onApplyConfiguration) throw new Error(t("source.operation.unavailable"));
      const result = await onApplyConfiguration(
        source.source_id,
        selectedStream.id,
        operationPreview.updates,
        operationPreview.preview_token
      );
      if (result.ok === false || result.error) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setReceipts((current) => [result, ...current.filter((item) => item.operation_id !== result.operation_id)]);
      setOperationPreview(null);
      onNotice(t("source.operation.applied", { id: result.operation_id }));
      onSourceChanged?.();
      setSection("history");
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const inspectRefresh = async () => {
    if (demo || !selectedStream) return;
    setOperationBusy(true);
    setOperationError("");
    setRefreshPreview(null);
    setRefreshReceipt(null);
    try {
      if (!onPreviewRefresh) throw new Error(t("source.operation.unavailable"));
      const result = await onPreviewRefresh(source.source_id, selectedStream.id, rawPath.trim());
      if (!result.ok) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setRefreshPreview(result);
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const executeRefresh = async () => {
    if (demo || !selectedStream || !refreshPreview?.preview_token) return;
    setOperationBusy(true);
    setOperationError("");
    try {
      if (!onRunRefresh) throw new Error(t("source.operation.unavailable"));
      const result = await onRunRefresh(
        source.source_id,
        selectedStream.id,
        rawPath.trim(),
        refreshPreview.preview_token
      );
      setRefreshReceipt(result);
      setReceipts((current) => [result, ...current.filter((item) => item.operation_id !== result.operation_id)]);
      if (!result.ok) {
        setOperationError(result.error || result.stderr || t("source.operation.failed"));
        return;
      }
      onNotice(t("source.refresh.complete", { id: result.operation_id }));
      onSourceChanged?.();
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const composeBrief = async () => {
    if (demo || !onComposeBrief || !onRequestBrief) return;
    // Compose from the server so the recipe grounding + stale-stream targeting
    // stay authoritative (mirrors the honest gate-fix flow).
    const result = await onRequestBrief(source.source_id);
    if (result.ok && result.spec) {
      onComposeBrief({ ...result.spec, agent: agentPreference });
    } else {
      onNotice(t("source.brief.failed", { error: result.error ?? "?" }));
    }
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside ref={dockRef} className="sourceDock worldDock" role="dialog" aria-label={t("source.title")}>
        <header className="dockHeader">
          <Database size={15} aria-hidden />
          <strong>{source.title}</strong>
          <span className={`pill pill-${syncTone}`}>{t(`source.sync.${source.sync.last_status}`)}</span>
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
            <X size={16} />
          </button>
        </header>

        <div className="sourceIdentity">
          <span className="sourceBadge">{source.platform || t("source.platform.unknown")}</span>
          {source.locator && <code className="sourceLocator">{source.locator}</code>}
          <small>
            {source.owner ? t("source.owner", { owner: source.owner }) : t("source.owner.none")}
            {source.context ? ` · ${contextLabel(source.context)}` : ""}
          </small>
        </div>

        <div className="sourceHealth" aria-label={t("source.health.aria")}>
          <DockTelemetryRail label={t("source.telemetry.aria")} items={sourceTelemetry([source])} />
          <span className="stripChip static">
            {t("source.health.fresh", { fresh: source.sync.streams_fresh, total: source.sync.streams_total })}
          </span>
          {source.pending_streams > 0 && (
            <span className="pill pill-warn">{t("source.health.pending", { n: source.pending_streams })}</span>
          )}
          {source.sync.last_run_at && (
            <small>
              {t("source.health.lastRun", { when: source.sync.last_run_at.replace("T", " ").slice(0, 16) })}
              {source.sync.derived_from_event ? ` · ${t("source.health.derived")}` : ""}
            </small>
          )}
          {source.schedule && source.schedule.mode !== "on_demand" && (
            <small>
              {t("source.schedule.mode." + source.schedule.mode)}
              {typeof source.next_due_days === "number"
                ? ` · ${source.next_due_days < 0 ? t("source.schedule.overdue", { n: -source.next_due_days }) : t("source.schedule.due", { n: source.next_due_days })}`
                : ""}
            </small>
          )}
        </div>

        <nav className="sourceWorkspaceTabs" aria-label={t("source.workspace.aria")}>
          {([
            ["records", File, "source.workspace.records"],
            ["update", Radio, "source.workspace.update"],
            ["configure", Settings2, "source.workspace.configure"],
            ["history", History, "source.workspace.history"]
          ] as const).map(([id, Icon, label]) => (
            <button
              key={id}
              type="button"
              className={section === id ? "active" : ""}
              aria-current={section === id ? "page" : undefined}
              onClick={() => setSection(id)}
            >
              <Icon size={14} aria-hidden />
              <span>{t(label)}</span>
            </button>
          ))}
        </nav>

        {/* §12.6: trace toggles — selection-driven highlights over the scene's
            real emission relations. Inspection only: nothing moves, nothing
            enters the URL, and toggling the active mode clears it. */}
        {section === "records" && onHighlightTrace && (
          <div className="sourceTrace" role="group" aria-label={t("source.trace.title")} title={t("source.trace.tip")}>
            <span>{t("source.trace.title")}</span>
            {TRACE_MODES.map((mode) => (
              <button
                key={mode}
                type="button"
                className={traceMode === mode ? "sourceTraceButton active" : "sourceTraceButton"}
                aria-pressed={traceMode === mode}
                onClick={() => onHighlightTrace(traceMode === mode ? null : mode)}
              >
                {t(`source.trace.${mode}`)}
              </button>
            ))}
          </div>
        )}

        {/* Auth is a POINTER, never a value — where the operator's credential lives. */}
        {section === "records" && source.auth && source.auth.method !== "none" && (
          <div className="sourceAuth" title={t("source.auth.tip")}>
            <Lock size={12} aria-hidden />
            <span>{t("source.auth.label", { method: source.auth.method })}</span>
            <code className="sourceAuthRef">{source.auth.ref}</code>
            {source.auth.scopes.length > 0 && <small>{source.auth.scopes.join(", ")}</small>}
          </div>
        )}

        {!source.recipe_ok && source.recipe_errors.length > 0 && (
          <div className="sourceRecipeError">
            <strong>{t("source.recipe.broken")}</strong>
            <ExpandablePre text={source.recipe_errors.join("\n")} title={t("source.recipe.broken")} />
          </div>
        )}

        {section === "records" && <div className="sourceSection sourceRecordsWorkspace">
          <h4>{t("source.streams.title", { n: selected.length })}</h4>
          <table className="sourceStreams">
            <thead>
              <tr>
                <th>{t("source.streams.channel")}</th>
                <th>{t("source.streams.freshness")}</th>
                <th>{t("source.streams.privacy")}</th>
              </tr>
            </thead>
            <tbody>
              {source.streams.map((stream) => (
                <tr
                  key={stream.id}
                  ref={(row) => {
                    if (row) streamRowRefs.current.set(stream.id, row);
                    else streamRowRefs.current.delete(stream.id);
                  }}
                  tabIndex={0}
                  data-stream-id={stream.id}
                  aria-selected={selectedStream?.id === stream.id}
                  onClick={() => setSelectedStreamId(stream.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedStreamId(stream.id);
                    }
                  }}
                  aria-label={t("source.stream.rowAria", {
                    id: stream.id,
                    freshness: stream.selected ? ageLabel(stream.cursor_age_days) : t("source.streams.unselected"),
                    cadence: stream.cadence_days ? t("source.streams.cadence", { n: stream.cadence_days }) : "—",
                    privacy: stream.privacy
                  })}
                  className={[
                    stream.breached ? "streamBreached" : stream.selected ? "" : "streamSkipped",
                    focusedStreamId === stream.id ? "streamFocused" : "",
                    selectedStream?.id === stream.id ? "streamSelected" : ""
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  <td>
                    <span className="sourceStreamName">
                      <File size={13} aria-hidden />
                      <span>
                        <strong>{stream.label || stream.id}</strong>
                        <code>{stream.id}</code>
                      </span>
                      {Boolean(stream.filters?.processing_state) && (
                        <span className="sourceStreamState">{String(stream.filters?.processing_state)}</span>
                      )}
                      <ChevronRight size={13} aria-hidden />
                    </span>
                  </td>
                  <td>
                    {stream.selected ? (
                      <span className={stream.breached ? "streamStale" : "streamFresh"}>
                        {ageLabel(stream.cursor_age_days)}
                        {stream.cadence_days ? ` / ${t("source.streams.cadence", { n: stream.cadence_days })}` : ""}
                      </span>
                    ) : (
                      <small>{t("source.streams.unselected")}</small>
                    )}
                  </td>
                  <td>
                    <small>{stream.privacy}</small>
                  </td>
                </tr>
              ))}
              {source.streams.length === 0 && (
                <tr>
                  <td colSpan={3}>
                    <small>{t("source.streams.none")}</small>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {selectedStream && (
            <section className="sourceRecord" aria-label={t("source.record.title")}>
              <header>
                <span>
                  <small>{t("source.record.eyebrow")}</small>
                  <strong>{selectedStream.label || selectedStream.id}</strong>
                </span>
                {Boolean(selectedStream.filters?.processing_state) && (
                  <span className="sourceRecordStatus">{String(selectedStream.filters?.processing_state)}</span>
                )}
              </header>
              <dl className="sourceRecordGrid">
                <dt>{t("source.record.id")}</dt>
                <dd><code>{selectedStream.id}</code></dd>
                {Boolean(selectedStream.filters?.file_id) && (
                  <>
                    <dt>{t("source.record.fileId")}</dt>
                    <dd><code>{String(selectedStream.filters?.file_id)}</code></dd>
                  </>
                )}
                {Boolean(selectedStream.filters?.mime_type) && (
                  <>
                    <dt>{t("source.record.mime")}</dt>
                    <dd>{String(selectedStream.filters?.mime_type)}</dd>
                  </>
                )}
                {selectedStream.filters?.size_bytes != null && (
                  <>
                    <dt>{t("source.record.size")}</dt>
                    <dd>{formatBytes(selectedStream.filters.size_bytes)}</dd>
                  </>
                )}
                {Boolean(selectedStream.filters?.created_at) && (
                  <>
                    <dt>{t("source.record.created")}</dt>
                    <dd>{formatWhen(String(selectedStream.filters?.created_at))}</dd>
                  </>
                )}
              </dl>
              {selectedStream.skip_reason && (
                <p className="sourceRecordReason">
                  <strong>{t("source.record.decision")}</strong> {selectedStream.skip_reason}
                </p>
              )}
              {selectedStream.target_pages.length > 0 && (
                <div className="sourceRecordTargets">
                  <small>{t("source.record.targets")}</small>
                  <div>
                    {selectedStream.target_pages.map((target) =>
                      onOpenPage ? (
                        <button key={target} onClick={() => onOpenPage(target)} type="button">{target}</button>
                      ) : (
                        <code key={target}>{target}</code>
                      )
                    )}
                  </div>
                </div>
              )}
              {selectedStream.filters && Object.keys(selectedStream.filters).length > 0 && (
                <details className="sourceRecordRaw">
                  <summary>{t("source.record.raw")}</summary>
                  <ExpandablePre text={JSON.stringify(selectedStream.filters, null, 2)} title={t("source.record.raw")} />
                </details>
              )}
            </section>
          )}
        </div>}

        {section === "update" && selectedStream && (
          <section className="sourceOperationWorkspace" aria-label={t("source.update.title")}>
            <header className="sourceOperationHeader">
              <span className="sourceOperationIcon"><Radio size={18} aria-hidden /></span>
              <span>
                <small>{t("source.update.eyebrow")}</small>
                <h3>{t("source.update.title")}</h3>
                <p>{t("source.update.intro")}</p>
              </span>
            </header>
            <div className="sourceSelectedContext">
              <span>
                <small>{t("source.record.eyebrow")}</small>
                <strong>{selectedStream.label || selectedStream.id}</strong>
                <code>{selectedStream.id}</code>
              </span>
              <button className="secondaryButton" type="button" onClick={() => setSection("records")}>
                <Pencil size={13} aria-hidden />
                {t("source.update.changeRecord")}
              </button>
            </div>
            <div className="sourceUpdateFlow" aria-label={t("source.update.flowAria")}>
              <article className="complete">
                <span>1</span>
                <strong>{t("source.update.step.inventory")}</strong>
                <small>{t("source.update.step.inventoryDetail")}</small>
              </article>
              <article className="current">
                <span>2</span>
                <strong>{t("source.update.step.collect")}</strong>
                <small>{t("source.update.step.collectDetail")}</small>
              </article>
              <article>
                <span>3</span>
                <strong>{t("source.update.step.review")}</strong>
                <small>{t("source.update.step.reviewDetail")}</small>
              </article>
              <article>
                <span>4</span>
                <strong>{t("source.update.step.integrate")}</strong>
                <small>{t("source.update.step.integrateDetail")}</small>
              </article>
            </div>
            <div className="sourceDeterministicCard">
              <header>
                <ClipboardCheck size={15} aria-hidden />
                <strong>{t("source.update.rawReady")}</strong>
                <span className="pill pill-good">{Object.keys(selectedStream.filters ?? {}).length}</span>
              </header>
              <dl>
                <dt>{t("source.record.fileId")}</dt>
                <dd><code>{String(selectedStream.filters?.file_id ?? "—")}</code></dd>
                <dt>{t("source.record.mime")}</dt>
                <dd>{String(selectedStream.filters?.mime_type ?? "—")}</dd>
                <dt>{t("source.record.created")}</dt>
                <dd>{selectedStream.filters?.created_at ? formatWhen(String(selectedStream.filters.created_at)) : "—"}</dd>
                <dt>{t("source.record.targets")}</dt>
                <dd>{selectedStream.target_pages.length}</dd>
              </dl>
              <details>
                <summary>{t("source.record.raw")}</summary>
                <ExpandablePre text={JSON.stringify(selectedStream.filters ?? {}, null, 2)} title={t("source.record.raw")} />
              </details>
            </div>
            <div className="sourceUpdateRoute">
              <div>
                <RefreshCw size={16} aria-hidden />
                <span>
                  <strong>{t("source.update.agentRoute")}</strong>
                  <small>{source.how_to_export || t("source.update.agentRouteDetail")}</small>
                </span>
              </div>
              {source.auth && source.auth.method !== "none" && (
                <p><Lock size={12} aria-hidden /> {t("source.auth.label", { method: source.auth.method })} · <code>{source.auth.ref}</code></p>
              )}
              <fieldset className="sourceAgentChoice">
                <legend>{t("source.update.agent")}</legend>
                <button type="button" className={agentPreference === "codex" ? "active" : ""} aria-pressed={agentPreference === "codex"} disabled={agentCapabilities ? !agentCapabilities.codex.usable : false} onClick={() => setAgentPreference("codex")}>Codex</button>
                <button type="button" className={agentPreference === "claude" ? "active" : ""} aria-pressed={agentPreference === "claude"} disabled={agentCapabilities ? !agentCapabilities.claude.usable : false} onClick={() => setAgentPreference("claude")}>Claude</button>
              </fieldset>
              {refreshPreview?.execution?.requires_agent && (
                <p className={connectorReady && agentReady ? "sourceConnectorReady" : "sourceConnectorBlocked"}>
                  {connectorReady && agentReady
                    ? t("source.update.connectorReady", { agent: agentPreference === "claude" ? "Claude" : "Codex" })
                    : t("source.update.connectorMissing", { connector: connectorHint || "MCP", agent: agentPreference === "claude" ? "Claude" : "Codex" })}
                </p>
              )}
            </div>
            <div className="sourceRefreshPlanner">
              <label>
                <span>{t("source.refresh.rawPath")}</span>
                <input
                  value={rawPath}
                  onChange={(event) => { setRawPath(event.target.value); setRefreshPreview(null); setRefreshReceipt(null); }}
                  placeholder="data/raw/..."
                />
                <small>{t("source.refresh.rawPathHint")}</small>
              </label>
              <button className="secondaryButton" type="button" onClick={() => void inspectRefresh()} disabled={demo || operationBusy}>
                {operationBusy ? <Loader2 className="sourceSpin" size={14} aria-hidden /> : <ClipboardCheck size={14} aria-hidden />}
                {t("source.refresh.inspect")}
              </button>
            </div>
            {refreshPreview?.ok && (
              <section className="sourceRefreshPlan" aria-label={t("source.refresh.plan")}>
                <header>
                  <CheckCircle2 size={15} aria-hidden />
                  <span><strong>{t("source.refresh.plan")}</strong><small>{t(`source.refresh.mode.${refreshPreview.execution?.mode ?? "manual_export"}`)}</small></span>
                </header>
                {refreshPreview.execution?.argv && refreshPreview.execution.argv.length > 0 && (
                  <code>{refreshPreview.execution.argv.join(" ")}</code>
                )}
                {refreshPreview.execution?.mcp_hint && <code>{refreshPreview.execution.mcp_hint}</code>}
                <ol>
                  {(refreshPreview.steps ?? []).map((step) => <li key={step.id} data-status={step.status}>{step.label}</li>)}
                </ol>
              </section>
            )}
            {refreshReceipt && (
              <section className="sourceRefreshOutput" aria-label={t("source.refresh.output")}>
                <header><CheckCircle2 size={15} aria-hidden /><strong>{t("source.refresh.output")}</strong><code>{refreshReceipt.operation_id}</code></header>
                <ExpandablePre text={[refreshReceipt.stdout, refreshReceipt.stderr].filter(Boolean).join("\n")} title={t("source.refresh.output")} />
              </section>
            )}
            {operationError && (
              <p className="sourceOperationError"><AlertTriangle size={14} aria-hidden /> {operationError}</p>
            )}
            <div className="dockActions sourceOperationActions">
              {!refreshPreview && (
                <button
                  className="btn btn--run"
                  onClick={() => void inspectRefresh()}
                  disabled={demo || operationBusy}
                  type="button"
                >
                  <ClipboardCheck size={14} aria-hidden />
                  <span>{t("source.refresh.inspect")}</span>
                </button>
              )}
              {refreshPreview?.execution?.requires_agent && onComposeBrief && (
                <button className="btn btn--run" onClick={composeBrief} disabled={demo || !agentReady || !connectorReady} type="button" title={!agentReady ? activeAgentCapability?.reason : !connectorReady ? t("source.update.connectorMissing", { connector: connectorHint || "MCP", agent: agentPreference === "claude" ? "Claude" : "Codex" }) : undefined}>
                  <RefreshCw size={14} aria-hidden />
                  <span>{t("source.update.prepare")}</span>
                </button>
              )}
              {refreshPreview?.execution?.runnable && (
                <button className="btn btn--run" onClick={() => void executeRefresh()} disabled={demo || operationBusy} type="button">
                  <Play size={14} aria-hidden />
                  <span>{t("source.refresh.runScript")}</span>
                </button>
              )}
              <button className="secondaryButton" onClick={() => setSection("configure")} type="button">
                <Settings2 size={14} aria-hidden />
                <span>{t("source.update.adjustFirst")}</span>
              </button>
            </div>
          </section>
        )}

        {section === "configure" && selectedStream && (
          <section className="sourceOperationWorkspace" aria-label={t("source.configure.title")}>
            <header className="sourceOperationHeader">
              <span className="sourceOperationIcon"><Settings2 size={18} aria-hidden /></span>
              <span>
                <small>{t("source.configure.eyebrow")}</small>
                <h3>{t("source.configure.title")}</h3>
                <p>{t("source.configure.intro")}</p>
              </span>
            </header>
            <div className="sourceSelectedContext">
              <span>
                <small>{t("source.record.eyebrow")}</small>
                <strong>{selectedStream.label || selectedStream.id}</strong>
                <code>{selectedStream.id}</code>
              </span>
              <button className="secondaryButton" type="button" onClick={() => setSection("records")}>
                <Pencil size={13} aria-hidden />
                {t("source.update.changeRecord")}
              </button>
            </div>
            <form className="sourceConfigForm" onSubmit={(event) => { event.preventDefault(); void previewConfiguration(); }}>
              <label>
                <span>{t("source.configure.label")}</span>
                <input value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} />
              </label>
              <label>
                <span>{t("source.configure.state")}</span>
                <input value={draft.processingState} onChange={(event) => setDraft({ ...draft, processingState: event.target.value })} />
              </label>
              <label>
                <span>{t("source.configure.privacy")}</span>
                <select value={draft.privacy} onChange={(event) => setDraft({ ...draft, privacy: event.target.value })}>
                  <option value="private_self">private_self</option>
                  <option value="private_sensitive_allowed">private_sensitive_allowed</option>
                  <option value="team_shared">team_shared</option>
                  <option value="public_ok">public_ok</option>
                </select>
              </label>
              <label>
                <span>{t("source.configure.cadence")}</span>
                <input type="number" min="0" max="3650" value={draft.cadenceDays} onChange={(event) => setDraft({ ...draft, cadenceDays: event.target.value })} />
              </label>
              <label className="sourceConfigWide sourceConfigToggle">
                <input type="checkbox" checked={draft.selected} onChange={(event) => setDraft({ ...draft, selected: event.target.checked })} />
                <span>{t("source.configure.selected")}</span>
              </label>
              <label className="sourceConfigWide">
                <span>{t("source.configure.skipReason")}</span>
                <textarea rows={2} value={draft.skipReason} onChange={(event) => setDraft({ ...draft, skipReason: event.target.value })} />
              </label>
              <label className="sourceConfigWide">
                <span>{t("source.configure.targets")}</span>
                <textarea rows={4} value={draft.targetPages} onChange={(event) => setDraft({ ...draft, targetPages: event.target.value })} />
                <small>{t("source.configure.targetsHint")}</small>
              </label>
              <div className="sourceConfigWide sourcePreviewAction">
                <button className="btn btn--run" type="submit" disabled={demo || operationBusy}>
                  {operationBusy ? <Loader2 className="sourceSpin" size={14} aria-hidden /> : <ClipboardCheck size={14} aria-hidden />}
                  {t("source.configure.preview")}
                </button>
                <small>{t("source.configure.previewHint")}</small>
              </div>
            </form>
            {operationError && (
              <p className="sourceOperationError"><AlertTriangle size={14} aria-hidden /> {operationError}</p>
            )}
            {operationPreview?.ok && (
              <section className="sourceReviewCard" aria-label={t("source.review.title")}>
                <header>
                  <CheckCircle2 size={16} aria-hidden />
                  <span><strong>{t("source.review.title")}</strong><small>{operationPreview.config_ref}</small></span>
                </header>
                <ol>
                  {(operationPreview.steps ?? []).map((step) => (
                    <li key={step.id} className={step.status === "complete" ? "complete" : "pending"}>
                      {step.status === "complete" ? <CheckCircle2 size={13} aria-hidden /> : <span />}
                      {step.label}
                    </li>
                  ))}
                </ol>
                <div className="sourceChangeList">
                  {(operationPreview.changes ?? []).map((change) => (
                    <div key={change.field}>
                      <strong>{change.field}</strong>
                      <code>{JSON.stringify(change.before)}</code>
                      <ChevronRight size={13} aria-hidden />
                      <code>{JSON.stringify(change.after)}</code>
                    </div>
                  ))}
                </div>
                <div className="sourceReviewConfirm">
                  <p><Lock size={12} aria-hidden /> {t("source.review.bound")}</p>
                  <button className="btn btn--run" type="button" onClick={() => void confirmConfiguration()} disabled={operationBusy}>
                    {operationBusy ? <Loader2 className="sourceSpin" size={14} aria-hidden /> : <Save size={14} aria-hidden />}
                    {t("source.review.apply")}
                  </button>
                </div>
              </section>
            )}
          </section>
        )}

        {/* §13.1 lifecycle parity — read-only projection resolved server-side
            (wiki_core/web/sources.py); the dock only renders what the payload
            already says. Raw vocabulary tokens are shown as code, never
            re-translated into something the server did not say. */}
        {section === "history" && source.lifecycle && (
          <div className="sourceSection sourceLifecycle">
            <h4>{t("source.lifecycle.title")}</h4>
            <dl className="sourceLifecycleGrid">
              {source.lifecycle.state && (
                <>
                  <dt>{t("source.lifecycle.state")}</dt>
                  <dd><code>{source.lifecycle.state}</code></dd>
                </>
              )}
              {source.lifecycle.pipeline_stage && (
                <>
                  <dt>{t("source.lifecycle.stage")}</dt>
                  <dd><code>{source.lifecycle.pipeline_stage}</code></dd>
                </>
              )}
              {source.lifecycle.adoption_state && (
                <>
                  <dt>{t("source.lifecycle.adoption")}</dt>
                  <dd><code>{source.lifecycle.adoption_state}</code></dd>
                </>
              )}
              {(source.lifecycle.last_attempt_state || source.lifecycle.last_attempt_at) && (
                <>
                  <dt>{t("source.lifecycle.lastAttempt")}</dt>
                  <dd>
                    {source.lifecycle.last_attempt_state && <code>{source.lifecycle.last_attempt_state}</code>}
                    {source.lifecycle.last_attempt_at && <small> {formatWhen(source.lifecycle.last_attempt_at)}</small>}
                  </dd>
                </>
              )}
              {source.lifecycle.accepted_ref && onOpenPage && (
                <>
                  <dt>{t("source.lifecycle.acceptedRef")}</dt>
                  <dd>
                    <button
                      className="sourceLifecycleLink"
                      onClick={() => onOpenPage(source.lifecycle!.accepted_ref)}
                      type="button"
                    >
                      {source.lifecycle.accepted_ref}
                    </button>
                  </dd>
                </>
              )}
              {source.lifecycle.reviewed_no_change_receipt && (
                <>
                  <dt>{t("source.lifecycle.receipt")}</dt>
                  <dd>
                    {onOpenPage ? (
                      <button
                        className="sourceLifecycleLink"
                        onClick={() => onOpenPage(source.lifecycle!.reviewed_no_change_receipt)}
                        type="button"
                      >
                        {source.lifecycle.reviewed_no_change_receipt}
                      </button>
                    ) : (
                      <code>{source.lifecycle.reviewed_no_change_receipt}</code>
                    )}
                  </dd>
                </>
              )}
            </dl>
            <p className="sourceLifecycleEmitted">
              {t("source.lifecycle.emitted", {
                pages: source.lifecycle.emitted_page_ids.length,
                actions: source.lifecycle.emitted_action_ids.length,
                proposals: source.lifecycle.proposal_ids.length
              })}
            </p>
            {source.lifecycle.emitted_page_ids.length > 0 && onOpenPage && (
              <div className="sourceLifecycleChips">
                {source.lifecycle.emitted_page_ids.slice(0, EMITTED_PAGE_LINK_BUDGET).map((pageId) => (
                  <button key={pageId} className="sourceLifecycleLink" onClick={() => onOpenPage(pageId)} type="button">
                    {pageId}
                  </button>
                ))}
                {source.lifecycle.emitted_page_ids.length > EMITTED_PAGE_LINK_BUDGET && (
                  <small>
                    {t("source.lifecycle.morePages", {
                      n: source.lifecycle.emitted_page_ids.length - EMITTED_PAGE_LINK_BUDGET
                    })}
                  </small>
                )}
              </div>
            )}
            {/* Closure summary of the newest ingestion event (§13.1). */}
            {source.sync.event_closure &&
              (source.sync.event_closure.gate_state ||
                source.sync.event_closure.consolidated_into.length > 0 ||
                source.sync.event_closure.reviewed_no_change) && (
                <p className="sourceLifecycleClosure">
                  <strong>{t("source.lifecycle.closure")}</strong>
                  {source.sync.event_closure.gate_state && (
                    <span> · {t("source.lifecycle.gate", { state: source.sync.event_closure.gate_state })}</span>
                  )}
                  {source.sync.event_closure.consolidated_into.length > 0 && (
                    <span>
                      {" "}· {t("source.lifecycle.consolidatedInto", { n: source.sync.event_closure.consolidated_into.length })}
                    </span>
                  )}
                  {source.sync.event_closure.reviewed_no_change && <span> · {t("source.lifecycle.noChange")}</span>}
                </p>
              )}
            {/* Safe diagnostic codes only — never free-form secrets. */}
            {(source.lifecycle.authoring_error_codes.length > 0 || source.lifecycle.blocked_reason) && (
              <div className="sourceLifecycleDiagnostics">
                <strong>{t("source.lifecycle.diagnostics")}</strong>
                {source.lifecycle.authoring_error_codes.map((code) => (
                  <code key={code}>{code}</code>
                ))}
                {source.lifecycle.blocked_reason && (
                  <small>{t("source.lifecycle.blockedReason", { reason: source.lifecycle.blocked_reason })}</small>
                )}
              </div>
            )}
          </div>
        )}

        {section === "history" && (
          <section className="sourceReceiptHistory" aria-label={t("source.history.title")}>
            <header><History size={15} aria-hidden /><strong>{t("source.history.title")}</strong><span>{receipts.length}</span></header>
            {receipts.length === 0 ? (
              <p>{t("source.history.empty")}</p>
            ) : (
              <ol>
                {receipts.map((receipt) => (
                  <li key={receipt.operation_id}>
                    <CheckCircle2 size={14} aria-hidden />
                    <span><strong>{receipt.stream_id}</strong><small>{formatWhen(receipt.recorded_at)} · {receipt.changes.length} {t("source.history.changes")}</small></span>
                    <code>{receipt.operation_id}</code>
                  </li>
                ))}
              </ol>
            )}
          </section>
        )}

        {section === "update" && source.how_to_export && (
          <details className="sourceSection sourceManual">
            <summary>{t("source.manual.title")}</summary>
            <ExpandablePre text={source.how_to_export} title={t("source.manual.title")} />
          </details>
        )}

        {section === "records" && <div className="dockActions">
          {onComposeBrief && (
            <button
              className="btn btn--run"
              onClick={composeBrief}
              disabled={demo || source.pending_streams === 0}
              aria-label={demo ? `${t("source.sync.action", { n: source.pending_streams })} — ${t("demo.readOnlyControl")}` : undefined}
              title={demo ? t("demo.readOnlyControl") : source.pending_streams === 0 ? t("source.brief.upToDate") : t("source.sync.tip")}
              type="button"
            >
              <RefreshCw size={14} />
              <span>{t("source.sync.action", { n: source.pending_streams })}</span>
            </button>
          )}
          {source.config_ref && onOpenPage && (
            <button className="secondaryButton" onClick={() => onOpenPage(source.config_ref)} type="button">
              <ExternalLink size={14} />
              <span>{t("source.openConfig")}</span>
            </button>
          )}
        </div>}
      </aside>
    </>
  );
}
