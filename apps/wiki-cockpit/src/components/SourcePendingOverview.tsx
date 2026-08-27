import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileInput,
  LoaderCircle,
  RefreshCw,
  ShieldCheck
} from "lucide-react";
import { t } from "../data/i18n";
import type { SourceEntity, SourceGroup, SourceOperationPreview, SourceOperationReceipt } from "../types";
import { SourcePlatformIcon } from "./SourcePlatformIcon";
import { sourceDisplayName, sourcePlatformLabel } from "./sourceDockModel";

type BatchState = "needs_path" | "preparing" | "ready" | "blocked" | "running" | "complete" | "failed";

type BatchItem = {
  source: SourceEntity;
  state: BatchState;
  rawPath: string;
  preview?: SourceOperationPreview;
  receipt?: SourceOperationReceipt;
  error?: string;
};

type SourcePendingOverviewProps = {
  sources: SourceEntity[];
  groups: SourceGroup[];
  demo?: boolean;
  onOpenSource?: (sourceId: string) => void;
  onPreviewRefresh?: (sourceId: string, streamId: string, rawPath?: string) => Promise<SourceOperationPreview>;
  onRunRefresh?: (
    sourceId: string,
    streamId: string,
    rawPath: string,
    previewToken: string,
    selectedExternalIds?: string[]
  ) => Promise<SourceOperationReceipt>;
  onSourceChanged?: () => void;
  onNotice: (text: string) => void;
};

function initialBatchItem(source: SourceEntity): BatchItem {
  if (!source.recipe_ok) return { source, state: "blocked", rawPath: "", error: t("source.pending.recipeBlocked") };
  if (source.update_route?.mode === "deterministic_connector") return { source, state: "preparing", rawPath: "" };
  if (source.update_route?.mode === "script") return { source, state: "needs_path", rawPath: "" };
  if (source.update_route?.mode === "agent_connector") return { source, state: "blocked", rawPath: "", error: t("source.pending.agentRequired") };
  return { source, state: "blocked", rawPath: "", error: t("source.pending.manualRequired") };
}

function statusLabel(item: BatchItem) {
  if (item.state === "needs_path") return t("source.pending.status.needsPath");
  if (item.state === "preparing") return t("source.pending.status.preparing");
  if (item.state === "ready") return t("source.pending.status.ready");
  if (item.state === "running") return t("source.pending.status.running");
  if (item.state === "complete") return t("source.pending.status.complete");
  if (item.state === "failed") return t("source.pending.status.failed");
  return t("source.pending.status.blocked");
}

function statusIcon(item: BatchItem) {
  if (item.state === "preparing" || item.state === "running") return <LoaderCircle className="sourcePendingSpin" size={16} aria-hidden />;
  if (item.state === "complete") return <CheckCircle2 size={16} aria-hidden />;
  if (item.state === "needs_path") return <FileInput size={16} aria-hidden />;
  if (item.state === "ready") return <ShieldCheck size={16} aria-hidden />;
  if (item.source.update_route?.requires_agent) return <Bot size={16} aria-hidden />;
  return <AlertTriangle size={16} aria-hidden />;
}

function actionableDiscoveryIds(preview?: SourceOperationPreview) {
  return (preview?.discovery?.records ?? [])
    .filter((record) => ["new", "changed", "enriched"].includes(record.status))
    .map((record) => record.external_id);
}

export function SourcePendingOverview({
  sources,
  groups,
  demo,
  onOpenSource,
  onPreviewRefresh,
  onRunRefresh,
  onSourceChanged,
  onNotice
}: SourcePendingOverviewProps) {
  const pending = useMemo(
    () => sources.filter((source) => source.pending_streams > 0)
      .sort((a, b) => b.pending_streams - a.pending_streams || a.title.localeCompare(b.title)),
    [sources]
  );
  const groupBySource = useMemo(() => {
    const result = new Map<string, string>();
    for (const group of groups) for (const sourceId of group.source_ids) result.set(sourceId, group.label);
    return result;
  }, [groups]);
  const [batchStarted, setBatchStarted] = useState(false);
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);

  const automatic = pending.filter((source) => source.recipe_ok && source.update_route?.mode === "deterministic_connector").length;
  const needsPath = pending.filter((source) => source.recipe_ok && source.update_route?.mode === "script").length;
  const delegated = Math.max(0, pending.length - automatic - needsPath);
  const readyCount = batchItems.filter((item) => item.state === "ready").length;
  const completeCount = batchItems.filter((item) => item.state === "complete").length;
  const failedCount = batchItems.filter((item) => item.state === "failed").length;

  const prepareItems = async (items: BatchItem[], shouldPrepare: (item: BatchItem) => boolean) => {
    const selectedIds = new Set(items.filter(shouldPrepare).map((item) => item.source.source_id));
    const selected = (item: BatchItem) => selectedIds.has(item.source.source_id);
    const marked = items.map((item) => selected(item) ? { ...item, state: "preparing" as const, error: "" } : item);
    setBatchItems(marked);
    if (!onPreviewRefresh) {
      setBatchItems(marked.map((item) => selected(item) ? { ...item, state: "failed", error: t("source.pending.unavailable") } : item));
      return;
    }
    const prepared = await Promise.all(marked.map(async (item): Promise<BatchItem> => {
      if (!selected(item)) return item;
      try {
        const preview = await onPreviewRefresh(item.source.source_id, "__source__", item.rawPath.trim());
        if (!preview.ok || !preview.preview_token) {
          return { ...item, state: "failed", error: preview.error || t("source.pending.previewFailed") };
        }
        return { ...item, state: "ready", preview };
      } catch (error) {
        return { ...item, state: "failed", error: error instanceof Error ? error.message : t("source.pending.previewFailed") };
      }
    }));
    setBatchItems(prepared);
  };

  const startBatch = async () => {
    if (demo || pending.length === 0 || batchBusy) return;
    setBatchBusy(true);
    setBatchStarted(true);
    const initial = pending.map(initialBatchItem);
    setBatchItems(initial);
    await prepareItems(initial, (item) => item.source.update_route?.mode === "deterministic_connector" && item.state === "preparing");
    setBatchBusy(false);
  };

  const preparePaths = async () => {
    if (batchBusy) return;
    setBatchBusy(true);
    await prepareItems(batchItems, (item) => item.state === "needs_path" && Boolean(item.rawPath.trim()));
    setBatchBusy(false);
  };

  const runPrepared = async () => {
    if (batchBusy || readyCount === 0 || !onRunRefresh) return;
    setBatchBusy(true);
    let current = [...batchItems];
    for (const candidate of current.filter((item) => item.state === "ready")) {
      current = current.map((item) => item.source.source_id === candidate.source.source_id ? { ...item, state: "running" } : item);
      setBatchItems(current);
      try {
        const receipt = await onRunRefresh(
          candidate.source.source_id,
          "__source__",
          candidate.rawPath.trim(),
          candidate.preview?.preview_token || "",
          actionableDiscoveryIds(candidate.preview)
        );
        current = current.map((item) => item.source.source_id === candidate.source.source_id
          ? { ...item, state: receipt.ok === false ? "failed" : "complete", receipt, error: receipt.ok === false ? receipt.error || receipt.stderr || t("source.pending.runFailed") : "" }
          : item);
      } catch (error) {
        current = current.map((item) => item.source.source_id === candidate.source.source_id
          ? { ...item, state: "failed", error: error instanceof Error ? error.message : t("source.pending.runFailed") }
          : item);
      }
      setBatchItems(current);
    }
    const completed = current.filter((item) => item.state === "complete").length;
    const failed = current.filter((item) => item.state === "failed").length;
    onNotice(t("source.pending.batchFinished", { completed, failed }));
    onSourceChanged?.();
    setBatchBusy(false);
  };

  const updateRawPath = (sourceId: string, rawPath: string) => {
    setBatchItems((items) => items.map((item) => item.source.source_id === sourceId
      ? { ...item, rawPath, state: item.state === "failed" ? "needs_path" : item.state, error: item.state === "failed" ? "" : item.error }
      : item));
  };

  return (
    <section className="sourcePendingOverview" aria-label={t("source.pending.title")}>
      <header className="sourcePendingHero">
        <div className="sourcePendingHeroCopy">
          <small>{t("source.pending.eyebrow")}</small>
          <h2>{pending.length > 0 ? t("source.pending.heading", { n: pending.length }) : t("source.pending.allFresh")}</h2>
          <p>{pending.length > 0 ? t("source.pending.intro") : t("source.pending.allFreshDetail")}</p>
        </div>
        <button className="btn btn--run sourcePendingRunAll" type="button" onClick={() => void startBatch()} disabled={demo || pending.length === 0 || batchBusy}>
          {batchBusy ? <LoaderCircle className="sourcePendingSpin" size={16} aria-hidden /> : <RefreshCw size={16} aria-hidden />}
          <span>{t("source.pending.updateAll", { n: pending.length })}</span>
        </button>
      </header>

      <div className="sourcePendingMetrics" aria-label={t("source.pending.readiness")}>
        <article><Clock3 size={17} aria-hidden /><span><strong>{pending.length}</strong><small>{t("source.pending.metric.pending")}</small></span></article>
        <article><ShieldCheck size={17} aria-hidden /><span><strong>{automatic}</strong><small>{t("source.pending.metric.automatic")}</small></span></article>
        <article><FileInput size={17} aria-hidden /><span><strong>{needsPath}</strong><small>{t("source.pending.metric.needsPath")}</small></span></article>
        <article><Bot size={17} aria-hidden /><span><strong>{delegated}</strong><small>{t("source.pending.metric.delegated")}</small></span></article>
      </div>

      {batchStarted && (
        <section className="sourceBatchPanel" aria-label={t("source.pending.batchTitle")}>
          <header>
            <div><small>{t("source.pending.batchEyebrow")}</small><h3>{t("source.pending.batchTitle")}</h3></div>
            <span>{completeCount}/{batchItems.length} {t("source.pending.completed")}</span>
          </header>
          <div className="sourceBatchProgress" aria-label={t("source.pending.progress", { completed: completeCount, total: batchItems.length })}>
            <i style={{ width: `${batchItems.length ? (completeCount / batchItems.length) * 100 : 0}%` }} />
          </div>
          <p>{t("source.pending.batchSafety")}</p>
          <ul className="sourceBatchList">
            {batchItems.map((item) => (
              <li key={item.source.source_id} className={`sourceBatchItem sourceBatchItem-${item.state}`}>
                <span className="sourcePendingIcon"><SourcePlatformIcon source={item.source} size={18} /></span>
                <span className="sourceBatchIdentity">
                  <strong>{sourceDisplayName(item.source.title)}</strong>
                  <small>{groupBySource.get(item.source.source_id) || t("source.pending.uncategorized")} · {item.source.pending_streams} {t("source.pending.records")}</small>
                </span>
                {item.state === "needs_path" ? (
                  <label className="sourceBatchPath">
                    <span>{t("source.pending.rawPath")}</span>
                    <input
                      value={item.rawPath}
                      onChange={(event) => updateRawPath(item.source.source_id, event.target.value)}
                      placeholder="data/raw/..."
                      aria-label={t("source.pending.rawPathFor", { name: sourceDisplayName(item.source.title) })}
                    />
                  </label>
                ) : (
                  <span className="sourceBatchStatus">{statusIcon(item)}<span>{statusLabel(item)}{item.error ? <small>{item.error}</small> : null}</span></span>
                )}
                <button type="button" className="sourcePendingOpen" onClick={() => onOpenSource?.(item.source.source_id)} aria-label={t("source.pending.openSource", { name: sourceDisplayName(item.source.title) })}>
                  <ChevronRight size={16} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
          <footer>
            <button className="secondaryButton" type="button" onClick={() => void preparePaths()} disabled={batchBusy || !batchItems.some((item) => item.state === "needs_path" && item.rawPath.trim())}>
              <ShieldCheck size={15} aria-hidden /> {t("source.pending.preparePaths")}
            </button>
            <button className="btn btn--run" type="button" onClick={() => void runPrepared()} disabled={batchBusy || readyCount === 0}>
              <RefreshCw size={15} aria-hidden /> {t("source.pending.runReady", { n: readyCount })}
            </button>
          </footer>
          {failedCount > 0 && <p className="sourceBatchFailure">{t("source.pending.failedCount", { n: failedCount })}</p>}
        </section>
      )}

      <section className="sourcePendingQueue" aria-label={t("source.pending.queueTitle")}>
        <header><div><small>{t("source.pending.queueEyebrow")}</small><h3>{t("source.pending.queueTitle")}</h3></div><span>{pending.length}</span></header>
        {pending.length === 0 ? (
          <div className="sourcePendingEmpty"><CheckCircle2 size={24} aria-hidden /><p>{t("source.pending.empty")}</p></div>
        ) : (
          <ul>
            {pending.map((source) => {
              const pendingStreams = source.streams.filter((stream) => stream.breached);
              const route = source.update_route?.mode;
              const routeLabel = route === "deterministic_connector"
                ? t("source.pending.route.automatic")
                : route === "script"
                  ? t("source.pending.route.raw")
                  : route === "agent_connector"
                    ? t("source.pending.route.agent")
                    : t("source.pending.route.manual");
              return (
                <li key={source.source_id}>
                  <span className="sourcePendingIcon"><SourcePlatformIcon source={source} size={20} /></span>
                  <span className="sourcePendingIdentity">
                    <strong>{sourceDisplayName(source.title)}</strong>
                    <small>{groupBySource.get(source.source_id) || t("source.pending.uncategorized")} · {sourcePlatformLabel(source.platform)}</small>
                  </span>
                  <span className="sourcePendingAge">
                    <strong>{pendingStreams.length || source.pending_streams}</strong>
                    <small>{t("source.pending.records")}</small>
                  </span>
                  <span className={`sourcePendingRoute sourcePendingRoute-${route || "manual_export"}`}>{routeLabel}</span>
                  <button type="button" className="sourcePendingOpen" onClick={() => onOpenSource?.(source.source_id)}>
                    {t("source.pending.inspect")} <ChevronRight size={15} aria-hidden />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </section>
  );
}
