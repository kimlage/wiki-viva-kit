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
import { DockTelemetryRail } from "./DockTelemetryRail";
import { ExpandablePre } from "./ExpandablePre";
import type { AgentCapabilities, BriefSpec, CodexJobRecord, SnapshotBundle, SourceEntity, SourceOperationPreview, SourceOperationReceipt } from "../types";
import {
  EMITTED_PAGE_LINK_BUDGET,
  SYNC_TONE,
  TRACE_MODES,
  formatBytes,
  formatWhen,
  scheduleModeLabel,
  sourceScopeCounts,
  sourceDisplayName,
  sourceKindLabel,
  sourcePlatformLabel,
  sourceTelemetry,
  streamFreshnessLabel,
  streamScopeLabel,
  type SourceSection,
  type SourceTraceMode
} from "./sourceDockModel";
import { useSourceOperations } from "./useSourceOperations";
import { SourceRunMonitor } from "./SourceRunMonitor";
import { SourcePlatformIcon } from "./SourcePlatformIcon";
import { SourceAuthorizationCard } from "./SourceAuthorizationCard";

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
  onListJobs,
  onStreamJobLog,
  onCancelJob,
  onSourceChanged,
  onNotice,
  onOpenPage,
  onOpenSource,
  onClose,
  embedded = false
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
  onRunRefresh?: (sourceId: string, streamId: string, rawPath: string, previewToken: string, selectedExternalIds?: string[]) => Promise<SourceOperationReceipt>;
  onListJobs?: (options?: { signal?: AbortSignal }) => Promise<CodexJobRecord[]>;
  onStreamJobLog?: (jobId: string, options?: { signal?: AbortSignal }) => Promise<string>;
  onCancelJob?: (jobId: string) => Promise<CodexJobRecord | null>;
  onSourceChanged?: () => void;
  onNotice: (text: string) => void;
  onOpenPage?: (pathOrId: string) => void;
  onOpenSource?: (id: string) => void;
  onClose: () => void;
  embedded?: boolean;
}) {
  const sources = bundle.sourceEntities?.sources ?? [];
  const source: SourceEntity | undefined = useMemo(
    () => (sourceId ? sources.find((s) => s.source_id === sourceId) : undefined),
    [sources, sourceId]
  );
  const [selectedStreamId, setSelectedStreamId] = useState("");
  const [section, setSection] = useState<SourceSection>("records");

  useEffect(() => {
    const streams = source?.streams ?? [];
    const focused = streams.find((stream) => stream.id === focusedStreamId);
    setSelectedStreamId(focused?.id ?? streams[0]?.id ?? "");
  }, [source?.source_id, focusedStreamId]);

  const {
    selectedStream,
    draft,
    setDraft,
    sourceDraft,
    setSourceDraft,
    operationPreview,
    operationBusy,
    operationError,
    receipts,
    agentPreference,
    setAgentPreference,
    rawPath,
    setRawPath,
    refreshPreview,
    setRefreshPreview,
    refreshReceipt,
    setRefreshReceipt,
    selectedDiscoveryIds,
    setSelectedDiscoveryIds,
    activeAgentCapability,
    connectorHint,
    connectorReady,
    agentReady,
    previewConfiguration,
    previewSourceConfiguration,
    confirmConfiguration,
    inspectRefresh,
    executeRefresh,
    composeBrief
  } = useSourceOperations({
    source,
    selectedStreamId,
    demo,
    agentCapabilities,
    onComposeBrief,
    onRequestBrief,
    onPreviewConfiguration,
    onApplyConfiguration,
    onListReceipts,
    onPreviewRefresh,
    onRunRefresh,
    onSourceChanged,
    onNotice,
    setSection
  });

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
        {!embedded && <div className="dockBackdrop" onClick={onClose} aria-hidden />}
        <aside ref={dockRef} className={`sourceDock worldDock${embedded ? " sourceDockEmbedded" : ""}`} role={embedded ? "region" : "dialog"} aria-label={t("source.list.title")}>
          <header className="dockHeader">
            <Database size={15} aria-hidden />
            <strong>{t("source.list.title", { n: sources.length })}</strong>
            {!embedded && <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button"><X size={16} /></button>}
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
                      <strong title={s.title}>{sourceDisplayName(s.title)}</strong>
                      <small>
                        <span className="sourceBadge sourceBadgeSm">{sourcePlatformLabel(s.platform)}</span>
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
        {!embedded && <div className="dockBackdrop" onClick={onClose} aria-hidden />}
        <aside ref={dockRef} className={`sourceDock worldDock${embedded ? " sourceDockEmbedded" : ""}`} role={embedded ? "region" : "dialog"} aria-label={t("source.title")}>
          <header className="dockHeader">
            <strong>{t("source.title")}</strong>
            {!embedded && <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button"><X size={16} /></button>}
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
  const recurring = source.schedule?.mode === "recurring";
  const scopeCounts = sourceScopeCounts(source.streams);
  const refreshPlanBlocked = Boolean(
    refreshPreview?.steps?.some((step) => step.status === "blocked") ||
    (refreshPreview?.execution?.requires_agent && (!connectorReady || !agentReady))
  );
  const updateRoute = refreshPreview?.execution ?? source.update_route;
  const selectedAgentName = agentPreference === "claude" ? "Claude" : "Codex";
  const showAgentChoice = updateRoute ? Boolean(updateRoute.requires_agent) : true;
  const refreshPanelKind = updateRoute?.mode === "script"
    ? "raw"
    : updateRoute?.mode === "deterministic_connector"
      ? "live"
      : updateRoute
        ? "route"
        : "fallback";
  const showRawPath = !updateRoute || updateRoute.mode === "script";
  const rawPathRequired = updateRoute?.mode === "script";

  return (
    <>
      {!embedded && <div className="dockBackdrop" onClick={onClose} aria-hidden />}
      <aside ref={dockRef} className={`sourceDock worldDock${embedded ? " sourceDockEmbedded" : ""}`} role={embedded ? "region" : "dialog"} aria-label={t("source.title")}>
        <header className="dockHeader">
          <SourcePlatformIcon source={source} size={16} />
          <strong title={source.title}>{sourceDisplayName(source.title)}</strong>
          <span className={`pill pill-${syncTone}`}>{t(`source.sync.${source.sync.last_status}`)}</span>
          {!embedded && <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button"><X size={16} /></button>}
        </header>

        <div className="sourceIdentity">
          <span className="sourceBadge">{sourcePlatformLabel(source.platform)}</span>
          <span className="sourceBadge">{sourceKindLabel(source.source_kind)}</span>
          <span className="sourceBadge">{scheduleModeLabel(source.schedule?.mode)}</span>
          {source.locator && <code className="sourceLocator">{source.locator}</code>}
          <small>
            {source.owner ? t("source.owner", { owner: source.owner }) : t("source.owner.none")}
            {source.context ? ` · ${contextLabel(source.context)}` : ""}
          </small>
        </div>

        <div className="sourceHealth" aria-label={t("source.health.aria")}>
          <DockTelemetryRail label={t("source.telemetry.aria")} items={sourceTelemetry([source])} />
          <span className="stripChip static">
            {t("source.health.scope", scopeCounts)}
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
          {source.schedule && (
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
          <h4>{t("source.streams.title", { n: source.streams.length })}</h4>
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
                    freshness: streamFreshnessLabel(stream, source.schedule?.mode),
                    cadence: recurring && stream.cadence_days ? t("source.streams.cadence", { n: stream.cadence_days }) : scheduleModeLabel(source.schedule?.mode),
                    privacy: stream.privacy
                  })}
                  className={[
                    recurring && stream.breached ? "streamBreached" : stream.selected ? "" : "streamSkipped",
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
                        <strong title={stream.label || stream.id}>{sourceDisplayName(stream.label || stream.id)}</strong>
                        <code>{stream.id}</code>
                      </span>
                      {Boolean(stream.filters?.processing_state) && (
                        <span className="sourceStreamState">{streamScopeLabel(stream)}</span>
                      )}
                      <ChevronRight size={13} aria-hidden />
                    </span>
                  </td>
                  <td>
                    {stream.selected ? (
                      <span className={recurring && stream.breached ? "streamStale" : "streamFresh"}>
                        {streamFreshnessLabel(stream, source.schedule?.mode)}
                      </span>
                    ) : (
                      <small>{streamScopeLabel(stream)}</small>
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
                  <strong title={selectedStream.label || selectedStream.id}>{sourceDisplayName(selectedStream.label || selectedStream.id)}</strong>
                </span>
                {Boolean(selectedStream.filters?.processing_state) && (
                  <span className="sourceRecordStatus">{streamScopeLabel(selectedStream)}</span>
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

        {section === "update" && (
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
                <small>{t("source.update.scopeEyebrow")}</small>
                <strong title={source.title}>{sourceDisplayName(source.title)}</strong>
                <code>{source.source_kind || source.platform} · {source.locator}</code>
              </span>
              <span className="pill pill-muted">{source.streams.length} {t("source.update.records")}</span>
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
                <span className="pill pill-good">{source.streams.length}</span>
              </header>
              <dl>
                <dt>{t("source.update.sourceKind")}</dt>
                <dd>{sourceKindLabel(source.source_kind)}</dd>
                <dt>{t("source.update.lifecycle")}</dt>
                <dd>{scheduleModeLabel(source.schedule?.mode)}</dd>
                <dt>{t("source.update.locator")}</dt>
                <dd><code>{source.locator || "—"}</code></dd>
                <dt>{t("source.update.records")}</dt>
                <dd>{source.streams.length}</dd>
              </dl>
              <details>
                <summary>{t("source.record.raw")}</summary>
                <ExpandablePre text={JSON.stringify(source.streams.map((stream) => ({ id: stream.id, selected: stream.selected, filters: stream.filters })), null, 2)} title={t("source.record.raw")} />
              </details>
            </div>
            <SourceAuthorizationCard
              source={source}
              route={updateRoute}
              agentName={selectedAgentName}
              agentCapabilitiesKnown={Boolean(agentCapabilities)}
              agentReady={agentReady}
              connectorReady={connectorReady}
              liveAccessVerified={Boolean(refreshPreview?.ok && refreshPreview.execution?.mode === "deterministic_connector")}
            />
            <div className="sourceUpdateRoute">
              <div>
                <RefreshCw size={16} aria-hidden />
                <span>
                  <strong>{t("source.update.agentRoute")}</strong>
                  <small>{source.how_to_export || t("source.update.agentRouteDetail")}</small>
                </span>
              </div>
              {showAgentChoice && (
                <fieldset className="sourceAgentChoice">
                  <legend>{t("source.update.agent")}</legend>
                  <button type="button" className={agentPreference === "codex" ? "active" : ""} aria-pressed={agentPreference === "codex"} disabled={agentCapabilities ? !agentCapabilities.codex.usable : false} onClick={() => setAgentPreference("codex")}>Codex</button>
                  <button type="button" className={agentPreference === "claude" ? "active" : ""} aria-pressed={agentPreference === "claude"} disabled={agentCapabilities ? !agentCapabilities.claude.usable : false} onClick={() => setAgentPreference("claude")}>Claude</button>
                </fieldset>
              )}
              {updateRoute?.requires_agent && (
                <p className={connectorReady && agentReady ? "sourceConnectorReady" : "sourceConnectorBlocked"}>
                  {connectorReady && agentReady
                    ? t("source.update.connectorReady", { agent: selectedAgentName })
                    : t("source.update.connectorMissing", { connector: connectorHint || "MCP", agent: selectedAgentName })}
                </p>
              )}
            </div>
            <div className="sourceRefreshFallback">
              <header>
                <small>{t(`source.refresh.panel.${refreshPanelKind}.eyebrow`)}</small>
                <strong>{t(`source.refresh.panel.${refreshPanelKind}.title`)}</strong>
                <p>{t(`source.refresh.panel.${refreshPanelKind}.intro`)}</p>
              </header>
              <div className={`sourceRefreshPlanner${showRawPath ? "" : " noInput"}`}>
                {showRawPath && <label>
                  <span>{t("source.refresh.rawPath")}</span>
                  <input
                    value={rawPath}
                    required={rawPathRequired}
                    aria-required={rawPathRequired}
                    onChange={(event) => { setRawPath(event.target.value); setRefreshPreview(null); setRefreshReceipt(null); }}
                    placeholder="data/raw/..."
                  />
                  <small>{t("source.refresh.rawPathHint")}</small>
                </label>}
                <button
                  className="secondaryButton"
                  type="button"
                  onClick={() => void inspectRefresh()}
                  disabled={demo || operationBusy || (rawPathRequired && !rawPath.trim())}
                  title={rawPathRequired && !rawPath.trim() ? t("source.refresh.rawRequired") : undefined}
                >
                  {operationBusy ? <Loader2 className="sourceSpin" size={14} aria-hidden /> : <ClipboardCheck size={14} aria-hidden />}
                  {t(updateRoute?.mode === "deterministic_connector" ? "source.refresh.inspectLive" : updateRoute?.mode === "script" ? "source.refresh.inspectRaw" : updateRoute?.mode === "manual_export" ? "source.refresh.inspectRoute" : "source.refresh.inspect")}
                </button>
              </div>
            </div>
            {refreshPreview?.ok && (
              <section className={`sourceRefreshPlan${refreshPlanBlocked ? " blocked" : ""}`} aria-label={t("source.refresh.plan")}>
                <header>
                  {refreshPlanBlocked ? <AlertTriangle size={15} aria-hidden /> : <CheckCircle2 size={15} aria-hidden />}
                  <span><strong>{t(refreshPlanBlocked ? "source.refresh.planBlocked" : "source.refresh.plan")}</strong><small>{t(`source.refresh.mode.${refreshPreview.execution?.mode ?? "manual_export"}`)}</small></span>
                </header>
                {refreshPreview.execution?.argv && refreshPreview.execution.argv.length > 0 && (
                  <code>{refreshPreview.execution.argv.join(" ")}</code>
                )}
                {refreshPreview.execution?.mcp_hint && <code>{refreshPreview.execution.mcp_hint}</code>}
                <ol>
                  {(refreshPreview.steps ?? []).map((step) => <li key={step.id} data-status={step.status}>{t(`source.refresh.step.${step.id}`)}</li>)}
                </ol>
                {refreshPreview.discovery && (
                  <div className="sourceDiscovery" aria-label={t("source.refresh.discovery.title")}>
                    <header>
                      <strong>{t("source.refresh.discovery.title")}</strong>
                      <span className="pill pill-info">{t("source.refresh.discovery.new", { n: refreshPreview.discovery.counts.new })}</span>
                      <span className="pill pill-warn">{t("source.refresh.discovery.changed", { n: refreshPreview.discovery.counts.changed })}</span>
                      <span className="pill pill-info">{t("source.refresh.discovery.enriched", { n: refreshPreview.discovery.counts.enriched })}</span>
                      <span className="pill pill-muted">{t("source.refresh.discovery.unchanged", { n: refreshPreview.discovery.counts.unchanged })}</span>
                    </header>
                    {refreshPreview.discovery.records.some((record) => record.status !== "unchanged") ? (
                      <ul>
                        {refreshPreview.discovery.records.filter((record) => record.status !== "unchanged").map((record) => (
                          <li key={record.external_id} data-status={record.status}>
                            <label>
                              <input
                                type="checkbox"
                                checked={selectedDiscoveryIds.includes(record.external_id)}
                                onChange={(event) => setSelectedDiscoveryIds(
                                  event.target.checked
                                    ? [...selectedDiscoveryIds, record.external_id]
                                    : selectedDiscoveryIds.filter((id) => id !== record.external_id)
                                )}
                              />
                              <span><strong>{record.label}</strong><small>{t(`source.refresh.discovery.status.${record.status}`)} · <code>{record.external_id}</code></small></span>
                            </label>
                            <details><summary>{t("source.record.raw")}</summary><ExpandablePre text={JSON.stringify(record.filters, null, 2)} title={record.label} /></details>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>{t("source.refresh.discovery.noChanges")}</p>
                    )}
                  </div>
                )}
              </section>
            )}
            {refreshReceipt && (
              <section className="sourceRefreshOutput" aria-label={t("source.refresh.output")}>
                <header><CheckCircle2 size={15} aria-hidden /><strong>{t("source.refresh.output")}</strong><small>{t(`source.history.status.${refreshReceipt.status}`)}</small><code>{refreshReceipt.operation_id}</code></header>
                {refreshReceipt.summary && (
                  <p className="sourceReceiptSummary">{t("source.history.inventorySummary", { new: refreshReceipt.summary.new, changed: refreshReceipt.summary.changed, enriched: refreshReceipt.summary.enriched, unchanged: refreshReceipt.summary.unchanged, applied: refreshReceipt.summary.applied })}</p>
                )}
                {(refreshReceipt.stdout || refreshReceipt.stderr) && <ExpandablePre text={[refreshReceipt.stdout, refreshReceipt.stderr].filter(Boolean).join("\n")} title={t("source.refresh.output")} />}
              </section>
            )}
            {operationError && (
              <p className="sourceOperationError"><AlertTriangle size={14} aria-hidden /> {operationError}</p>
            )}
            <div className="dockActions sourceOperationActions">
              {refreshPreview?.execution?.requires_agent && onComposeBrief && (
                <button className="btn btn--run" onClick={composeBrief} disabled={demo || !agentReady || !connectorReady} type="button" title={!agentReady ? activeAgentCapability?.reason : !connectorReady ? t("source.update.connectorMissing", { connector: connectorHint || "MCP", agent: agentPreference === "claude" ? "Claude" : "Codex" }) : undefined}>
                  <RefreshCw size={14} aria-hidden />
                  <span>{t("source.update.prepare")}</span>
                </button>
              )}
              {refreshPreview?.execution?.runnable && (
                <button className="btn btn--run" onClick={() => void executeRefresh()} disabled={demo || operationBusy || Boolean(refreshPreview.discovery && refreshPreview.discovery.counts.new + refreshPreview.discovery.counts.changed + refreshPreview.discovery.counts.enriched > 0 && selectedDiscoveryIds.length === 0)} type="button">
                  <Play size={14} aria-hidden />
                  <span>{t(refreshPreview.execution.mode === "deterministic_connector" ? (refreshPreview.discovery && refreshPreview.discovery.counts.new + refreshPreview.discovery.counts.changed + refreshPreview.discovery.counts.enriched === 0 ? "source.refresh.recordCheck" : refreshPreview.discovery && refreshPreview.discovery.counts.new + refreshPreview.discovery.counts.changed === 0 ? "source.refresh.saveMetadata" : "source.refresh.applyInventory") : "source.refresh.runScript")}</span>
                </button>
              )}
              <button className="secondaryButton" onClick={() => setSection("configure")} type="button">
                <Settings2 size={14} aria-hidden />
                <span>{t("source.update.adjustFirst")}</span>
              </button>
            </div>
            <SourceRunMonitor
              sourceId={source.source_id}
              demo={demo}
              onListJobs={onListJobs}
              onStreamJobLog={onStreamJobLog}
              onCancelJob={onCancelJob}
            />
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
            <form className="sourceConfigForm sourceLevelConfig" onSubmit={(event) => { event.preventDefault(); void previewSourceConfiguration(); }}>
              <div className="sourceConfigWide sourceConfigHeading">
                <span>
                  <small>{t("source.configure.sourceEyebrow")}</small>
                  <strong>{t("source.configure.sourceTitle")}</strong>
                </span>
                <small>{t("source.configure.sourceHint")}</small>
              </div>
              <label>
                <span>{t("source.configure.sourceKind")}</span>
                <select value={sourceDraft.sourceKind} onChange={(event) => setSourceDraft({ ...sourceDraft, sourceKind: event.target.value as typeof sourceDraft.sourceKind })}>
                  <option value="item">{t("source.kind.item")}</option>
                  <option value="collection">{t("source.kind.collection")}</option>
                  <option value="account">{t("source.kind.account")}</option>
                  <option value="endpoint">{t("source.kind.endpoint")}</option>
                  <option value="repository">{t("source.kind.repository")}</option>
                </select>
              </label>
              <label>
                <span>{t("source.configure.scheduleMode")}</span>
                <select value={sourceDraft.scheduleMode} onChange={(event) => {
                  const scheduleMode = event.target.value as typeof sourceDraft.scheduleMode;
                  setSourceDraft({ ...sourceDraft, scheduleMode, scheduleCadenceDays: scheduleMode === "recurring" ? sourceDraft.scheduleCadenceDays || "7" : "0" });
                }}>
                  <option value="one_shot">{t("source.schedule.mode.one_shot")}</option>
                  <option value="on_demand">{t("source.schedule.mode.on_demand")}</option>
                  <option value="recurring">{t("source.schedule.mode.recurring")}</option>
                  <option value="event_driven">{t("source.schedule.mode.event_driven")}</option>
                </select>
              </label>
              <label>
                <span>{t("source.configure.cadence")}</span>
                <input type="number" min="1" max="3650" value={sourceDraft.scheduleCadenceDays} disabled={sourceDraft.scheduleMode !== "recurring"} onChange={(event) => setSourceDraft({ ...sourceDraft, scheduleCadenceDays: event.target.value })} />
                <small>{sourceDraft.scheduleMode === "recurring" ? t("source.configure.cadenceRecurringHint") : t("source.configure.cadenceDisabledHint")}</small>
              </label>
              <div className="sourceConfigWide sourcePreviewAction">
                <button className="btn btn--run" type="submit" disabled={demo || operationBusy}>
                  {operationBusy ? <Loader2 className="sourceSpin" size={14} aria-hidden /> : <ClipboardCheck size={14} aria-hidden />}
                  {t("source.configure.previewSource")}
                </button>
              </div>
            </form>
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
              {recurring && <label>
                <span>{t("source.configure.recordCadence")}</span>
                <input type="number" min="1" max="3650" value={draft.cadenceDays} onChange={(event) => setDraft({ ...draft, cadenceDays: event.target.value })} />
              </label>}
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
                      {t(`source.operation.step.${step.id}`)}
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
            {source.lifecycle.derived_from_legacy && (
              <p className="sourceLifecycleDerived">{t("source.lifecycle.derivedLegacy")}</p>
            )}
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
                    <span><strong>{receipt.stream_id === "__source__" ? t("source.history.sourceScope") : receipt.stream_id}</strong><small>{formatWhen(receipt.recorded_at)} · {t(`source.history.status.${receipt.status}`)}</small>{receipt.summary && <small>{t("source.history.inventorySummary", { new: receipt.summary.new, changed: receipt.summary.changed, enriched: receipt.summary.enriched, unchanged: receipt.summary.unchanged, applied: receipt.summary.applied })}</small>}</span>
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
