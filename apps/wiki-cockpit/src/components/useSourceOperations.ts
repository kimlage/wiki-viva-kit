import { useEffect, useState } from "react";
import { t } from "../data/i18n";
import type {
  AgentCapabilities,
  BriefSpec,
  SourceEntity,
  SourceOperationPreview,
  SourceOperationReceipt
} from "../types";
import { collectSourceUpdates, collectStreamUpdates, EMPTY_DRAFT, EMPTY_SOURCE_DRAFT, type SourceDraft, type SourceSection, type StreamDraft } from "./sourceDockModel";

type SourceOperationsOptions = {
  source?: SourceEntity;
  selectedStreamId: string;
  demo: boolean;
  agentCapabilities?: AgentCapabilities;
  onComposeBrief?: (spec: BriefSpec) => void;
  onRequestBrief?: (sourceId: string) => Promise<{ ok: boolean; spec?: BriefSpec; error?: string }>;
  onPreviewConfiguration?: (sourceId: string, streamId: string, updates: Record<string, unknown>) => Promise<SourceOperationPreview>;
  onApplyConfiguration?: (sourceId: string, streamId: string, updates: Record<string, unknown>, previewToken: string) => Promise<SourceOperationReceipt>;
  onListReceipts?: (sourceId: string, options?: { signal?: AbortSignal }) => Promise<SourceOperationReceipt[]>;
  onPreviewRefresh?: (sourceId: string, streamId: string, rawPath?: string) => Promise<SourceOperationPreview>;
  onRunRefresh?: (sourceId: string, streamId: string, rawPath: string, previewToken: string, selectedExternalIds?: string[]) => Promise<SourceOperationReceipt>;
  onSourceChanged?: () => void;
  onNotice: (text: string) => void;
  setSection: (section: SourceSection) => void;
};

export function useSourceOperations({
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
}: SourceOperationsOptions) {
  const selectedStream = source?.streams.find((stream) => stream.id === selectedStreamId) ?? source?.streams[0];
  const selectedStreamRevision = JSON.stringify({
    label: selectedStream?.label,
    selected: selectedStream?.selected,
    privacy: selectedStream?.privacy,
    cadenceDays: selectedStream?.cadence_days,
    processingState: selectedStream?.filters?.processing_state,
    skipReason: selectedStream?.skip_reason,
    targetPages: selectedStream?.target_pages
  });
  const [draft, setDraft] = useState<StreamDraft>(EMPTY_DRAFT);
  const [sourceDraft, setSourceDraft] = useState<SourceDraft>(EMPTY_SOURCE_DRAFT);
  const [operationPreview, setOperationPreview] = useState<SourceOperationPreview | null>(null);
  const [operationTargetId, setOperationTargetId] = useState("");
  const [operationBusy, setOperationBusy] = useState(false);
  const [operationError, setOperationError] = useState("");
  const [receipts, setReceipts] = useState<SourceOperationReceipt[]>([]);
  const [agentPreference, setAgentPreference] = useState<"codex" | "claude">("codex");
  const [rawPath, setRawPath] = useState("");
  const [refreshPreview, setRefreshPreview] = useState<SourceOperationPreview | null>(null);
  const [refreshReceipt, setRefreshReceipt] = useState<SourceOperationReceipt | null>(null);
  const [selectedDiscoveryIds, setSelectedDiscoveryIds] = useState<string[]>([]);

  useEffect(() => {
    if (!selectedStream) {
      setDraft(EMPTY_DRAFT);
      return;
    }
    setDraft({
      label: selectedStream.label || selectedStream.id,
      selected: selectedStream.selected,
      privacy: selectedStream.privacy,
      cadenceDays: String(selectedStream.cadence_days ?? 0),
      processingState: String(selectedStream.filters?.processing_state ?? ""),
      skipReason: selectedStream.skip_reason ?? "",
      targetPages: selectedStream.target_pages.join("\n")
    });
    setOperationPreview(null);
    setOperationError("");
    setRefreshPreview(null);
    setRefreshReceipt(null);
    setSelectedDiscoveryIds([]);
    setRawPath("");
  }, [selectedStream?.id, source?.source_id, selectedStreamRevision]);

  useEffect(() => {
    if (!source) {
      setSourceDraft(EMPTY_SOURCE_DRAFT);
      return;
    }
    setSourceDraft({
      sourceKind: source.source_kind || "collection",
      scheduleMode: (source.schedule?.mode as SourceDraft["scheduleMode"]) || "on_demand",
      scheduleCadenceDays: String(source.schedule?.cadence_days ?? 0)
    });
    setOperationPreview(null);
    setOperationTargetId("");
    setOperationError("");
  }, [source?.source_id, source?.source_kind, source?.schedule?.mode, source?.schedule?.cadence_days]);

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

  const activeAgentCapability = agentCapabilities?.[agentPreference];
  const connectorHint = refreshPreview?.execution?.mcp_hint ?? "";
  const connectorKey = connectorHint.split(/[./]/, 1)[0].replace(/[^a-z0-9]/gi, "").toLowerCase();
  const connectorReady = !refreshPreview?.execution?.requires_agent || !agentCapabilities || Boolean(
    activeAgentCapability?.connectors?.some(
      (name) => name.replace(/[^a-z0-9]/gi, "").toLowerCase() === connectorKey
    )
  );
  const agentReady = !agentCapabilities || Boolean(activeAgentCapability?.usable);

  const previewConfiguration = async () => {
    if (demo || !source || !selectedStream) return;
    setOperationBusy(true);
    setOperationError("");
    setOperationPreview(null);
    try {
      if (!onPreviewConfiguration) throw new Error(t("source.operation.unavailable"));
      const result = await onPreviewConfiguration(
        source.source_id,
        selectedStream.id,
        collectStreamUpdates(selectedStream, draft)
      );
      if (!result.ok) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setOperationTargetId(selectedStream.id);
      setOperationPreview(result);
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const previewSourceConfiguration = async () => {
    if (demo || !source) return;
    setOperationBusy(true);
    setOperationError("");
    setOperationPreview(null);
    try {
      if (!onPreviewConfiguration) throw new Error(t("source.operation.unavailable"));
      const updates = collectSourceUpdates(source, sourceDraft);
      if (Object.keys(updates).length === 0) throw new Error(t("source.operation.noChanges"));
      const result = await onPreviewConfiguration(source.source_id, "__source__", updates);
      if (!result.ok) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setOperationTargetId("__source__");
      setOperationPreview(result);
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const confirmConfiguration = async () => {
    if (demo || !source || !operationTargetId || !operationPreview?.preview_token || !operationPreview.updates) return;
    setOperationBusy(true);
    setOperationError("");
    try {
      if (!onApplyConfiguration) throw new Error(t("source.operation.unavailable"));
      const result = await onApplyConfiguration(
        source.source_id,
        operationTargetId,
        operationPreview.updates,
        operationPreview.preview_token
      );
      if (result.ok === false || result.error) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setReceipts((current) => [result, ...current.filter((item) => item.operation_id !== result.operation_id)]);
      setOperationPreview(null);
      setOperationTargetId("");
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
    if (demo || !source) return;
    setOperationBusy(true);
    setOperationError("");
    setRefreshPreview(null);
    setRefreshReceipt(null);
    try {
      if (!onPreviewRefresh) throw new Error(t("source.operation.unavailable"));
      const result = await onPreviewRefresh(source.source_id, "__source__", rawPath.trim());
      if (!result.ok) {
        setOperationError(result.error || t("source.operation.failed"));
        return;
      }
      setRefreshPreview(result);
      setSelectedDiscoveryIds(
        (result.discovery?.records ?? [])
          .filter((record) => record.status === "new" || record.status === "changed" || record.status === "enriched")
          .map((record) => record.external_id)
      );
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const executeRefresh = async () => {
    if (demo || !source || !refreshPreview?.preview_token) return;
    setOperationBusy(true);
    setOperationError("");
    try {
      if (!onRunRefresh) throw new Error(t("source.operation.unavailable"));
      const result = await onRunRefresh(
        source.source_id,
        "__source__",
        rawPath.trim(),
        refreshPreview.preview_token,
        selectedDiscoveryIds
      );
      setRefreshReceipt(result);
      setReceipts((current) => [result, ...current.filter((item) => item.operation_id !== result.operation_id)]);
      if (!result.ok) {
        setOperationError(result.error || result.stderr || t("source.operation.failed"));
        return;
      }
      onNotice(t("source.refresh.complete", { id: result.operation_id }));
      setRefreshPreview(null);
      setSelectedDiscoveryIds([]);
      onSourceChanged?.();
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : t("source.operation.failed"));
    } finally {
      setOperationBusy(false);
    }
  };

  const composeBrief = async () => {
    if (demo || !source || !onComposeBrief || !onRequestBrief) return;
    const result = await onRequestBrief(source.source_id);
    if (result.ok && result.spec) onComposeBrief({ ...result.spec, agent: agentPreference });
    else onNotice(t("source.brief.failed", { error: result.error ?? "?" }));
  };

  return {
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
  };
}
