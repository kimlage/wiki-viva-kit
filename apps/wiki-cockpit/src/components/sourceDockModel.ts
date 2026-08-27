import { t } from "../data/i18n";
import type { SourceEntity } from "../types";
import type { DockTelemetryItem } from "./DockTelemetryRail";

export type SourceSection = "records" | "update" | "configure" | "history";
export type SourceTraceMode = "upstream" | "downstream" | "closure";

export type StreamDraft = {
  label: string;
  selected: boolean;
  privacy: string;
  cadenceDays: string;
  processingState: string;
  skipReason: string;
  targetPages: string;
};

export type SourceDraft = {
  sourceKind: "item" | "collection" | "account" | "endpoint" | "repository";
  scheduleMode: "one_shot" | "on_demand" | "recurring" | "event_driven";
  scheduleCadenceDays: string;
};

export const EMPTY_DRAFT: StreamDraft = {
  label: "",
  selected: true,
  privacy: "private_self",
  cadenceDays: "0",
  processingState: "",
  skipReason: "",
  targetPages: ""
};

export const EMPTY_SOURCE_DRAFT: SourceDraft = {
  sourceKind: "collection",
  scheduleMode: "on_demand",
  scheduleCadenceDays: "0"
};

export const TRACE_MODES: SourceTraceMode[] = ["upstream", "downstream", "closure"];
export const EMITTED_PAGE_LINK_BUDGET = 5;

export function formatWhen(when: string): string {
  return when.replace("T", " ").slice(0, 16);
}

export const SYNC_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  ok: "good",
  partial: "warn",
  running: "muted",
  queued: "muted",
  failed: "bad",
  never: "muted"
};

export function ageLabel(days: number | null): string {
  if (days === null) return t("source.stream.never");
  if (days <= 0) return t("source.stream.today");
  return t("source.stream.daysAgo", { n: days });
}

export type StreamScopeState = "active" | "covered" | "excluded";

export function streamScopeState(stream: SourceEntity["streams"][number]): StreamScopeState {
  if (stream.selected) return "active";
  const processingState = String(stream.filters?.processing_state ?? "").trim().toLowerCase();
  return processingState === "covered" ? "covered" : "excluded";
}

export function streamScopeLabel(stream: SourceEntity["streams"][number]): string {
  const state = streamScopeState(stream);
  if (state === "covered") return t("source.streams.covered");
  if (state === "excluded") return t("source.streams.excluded");
  return String(stream.filters?.processing_state ?? "").trim();
}

export function streamFreshnessLabel(
  stream: SourceEntity["streams"][number],
  scheduleMode: string | undefined
): string {
  if (!stream.selected) return streamScopeLabel(stream);
  const processingState = String(stream.filters?.processing_state ?? "").trim().toLowerCase();
  if (processingState === "discovered" || processingState === "changed" || processingState === "pending" || processingState === "queued") {
    return t(`source.streams.processing.${processingState}`);
  }
  if (scheduleMode === "one_shot") {
    return `${t("source.streams.completed")} / ${scheduleModeLabel(scheduleMode)}`;
  }
  const cadence = scheduleMode === "recurring" && stream.cadence_days
    ? t("source.streams.cadence", { n: stream.cadence_days })
    : scheduleModeLabel(scheduleMode);
  const age = ageLabel(stream.cursor_age_days);
  return `${scheduleMode === "recurring" ? age : t("source.streams.lastCapture", { age })} / ${cadence}`;
}

export function sourceScopeCounts(streams: SourceEntity["streams"]): {
  active: number;
  covered: number;
  excluded: number;
} {
  return streams.reduce(
    (counts, stream) => {
      counts[streamScopeState(stream)] += 1;
      return counts;
    },
    { active: 0, covered: 0, excluded: 0 }
  );
}

export function sourceKindLabel(kind: SourceEntity["source_kind"]): string {
  return t(`source.kind.${kind || "collection"}`);
}

export function scheduleModeLabel(mode: string | undefined): string {
  return t(`source.schedule.mode.${mode || "on_demand"}`);
}

export function formatBytes(value: unknown): string {
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

export function sourceTelemetry(sources: SourceEntity[]): DockTelemetryItem[] {
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

export function collectStreamUpdates(
  stream: SourceEntity["streams"][number] | undefined,
  draft: StreamDraft
): Record<string, unknown> {
  if (!stream) return {};
  const values: Record<string, unknown> = {
    label: draft.label.trim(),
    selected: draft.selected,
    privacy: draft.privacy,
    cadence_days: Number(draft.cadenceDays || 0),
    processing_state: draft.processingState.trim(),
    skip_reason: draft.skipReason.trim(),
    target_pages: draft.targetPages.split("\n").map((item) => item.trim()).filter(Boolean)
  };
  const current: Record<string, unknown> = {
    label: stream.label || stream.id,
    selected: stream.selected,
    privacy: stream.privacy,
    cadence_days: stream.cadence_days ?? 0,
    processing_state: String(stream.filters?.processing_state ?? ""),
    skip_reason: stream.skip_reason ?? "",
    target_pages: stream.target_pages
  };
  return Object.fromEntries(
    Object.entries(values).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(current[key]))
  );
}

export function collectSourceUpdates(source: SourceEntity | undefined, draft: SourceDraft): Record<string, unknown> {
  if (!source) return {};
  const cadence = draft.scheduleMode === "recurring" ? Number(draft.scheduleCadenceDays || 0) : 0;
  const values: Record<string, unknown> = {
    source_kind: draft.sourceKind,
    schedule_mode: draft.scheduleMode,
    schedule_cadence_days: cadence
  };
  const current: Record<string, unknown> = {
    source_kind: source.source_kind || "collection",
    schedule_mode: source.schedule?.mode || "on_demand",
    schedule_cadence_days: source.schedule?.cadence_days ?? 0
  };
  return Object.fromEntries(
    Object.entries(values).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(current[key]))
  );
}
