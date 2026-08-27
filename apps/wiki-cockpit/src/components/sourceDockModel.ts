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

export const EMPTY_DRAFT: StreamDraft = {
  label: "",
  selected: true,
  privacy: "private_self",
  cadenceDays: "0",
  processingState: "",
  skipReason: "",
  targetPages: ""
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
