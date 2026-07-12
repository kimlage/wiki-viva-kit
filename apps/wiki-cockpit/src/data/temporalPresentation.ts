import type { TemporalEvent } from "../types";

export const TEMPORAL_LANE_IDS = [
  "source",
  "action",
  "decision",
  "receipt",
  "page",
  "system",
  "other"
] as const;

export type TemporalLaneId = (typeof TEMPORAL_LANE_IDS)[number];
export type TemporalTimeMode = "event" | "occurred" | "recorded";

const SOURCE_KINDS = /^(source_|ingestion_)/;

export function temporalLane(event: Pick<TemporalEvent, "kind" | "lane">): TemporalLaneId {
  if (event.lane && TEMPORAL_LANE_IDS.includes(event.lane)) return event.lane;
  if (SOURCE_KINDS.test(event.kind)) return "source";
  if (event.kind.startsWith("action_")) return "action";
  if (event.kind.startsWith("decision_")) return "decision";
  if (event.kind.startsWith("receipt_")) return "receipt";
  if (event.kind.startsWith("page_")) return "page";
  if (/^(activity_|snapshot_|git_)/.test(event.kind)) return "system";
  return "other";
}

export function temporalValueForMode(
  event: TemporalEvent,
  mode: TemporalTimeMode
): string | null {
  // Every mode is intentionally strict. `event` is the compiler-declared
  // semantic anchor (created/due/ingested/etc.); occurred and recorded never
  // borrow another clock. Mixing them would rewrite missing history as fact.
  if (mode === "event") return event.anchor?.value || null;
  if (mode === "recorded") return event.recorded_at || null;
  return event.occurred_at || null;
}

function dayBounds(value: string | null): { from: string; to: string } | null {
  if (!value) return null;
  if (/^\d{4}$/.test(value)) return { from: `${value}-01-01`, to: `${value}-12-31` };
  if (/^\d{4}-\d{2}$/.test(value)) {
    const [year, month] = value.split("-").map(Number);
    if (!year || !month || month > 12) return null;
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return { from: `${value}-01`, to: `${value}-${String(lastDay).padStart(2, "0")}` };
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return { from: value, to: value };
  const instant = Date.parse(value);
  if (!Number.isFinite(instant)) return null;
  const day = new Date(instant).toISOString().slice(0, 10);
  return { from: day, to: day };
}

function instantMicros(value: string): bigint | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return null;
  const base = `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}${match[8]}`;
  const millis = Date.parse(base);
  if (!Number.isFinite(millis)) return null;
  return BigInt(millis) * 1000n + BigInt((match[7] || "").padEnd(6, "0") || "0");
}

export function compareTemporalValuesDescending(left: string, right: string): number {
  const leftMicros = instantMicros(left);
  const rightMicros = instantMicros(right);
  if (leftMicros !== null && rightMicros !== null) {
    if (leftMicros < rightMicros) return 1;
    if (leftMicros > rightMicros) return -1;
    return 0;
  }
  return right.localeCompare(left);
}

export type TemporalFilter = {
  mode: TemporalTimeMode;
  from?: string;
  to?: string;
  lanes?: readonly string[];
};

export function filterTemporalEvents(
  events: readonly TemporalEvent[],
  filter: TemporalFilter
): TemporalEvent[] {
  const lanes = new Set(filter.lanes?.filter(Boolean) ?? []);
  return events
    .filter((event) => lanes.size === 0 || lanes.has(temporalLane(event)))
    .filter((event) => {
      if (!filter.from && !filter.to) return true;
      const bounds = dayBounds(temporalValueForMode(event, filter.mode));
      if (!bounds) return false;
      if (filter.from && bounds.to < filter.from) return false;
      if (filter.to && bounds.from > filter.to) return false;
      return true;
    })
    .sort((left, right) => {
      const leftValue = temporalValueForMode(left, filter.mode) || "";
      const rightValue = temporalValueForMode(right, filter.mode) || "";
      return compareTemporalValuesDescending(leftValue, rightValue) || left.event_id.localeCompare(right.event_id);
    });
}

export function pageIdFromTemporalRef(ref: string): string | null {
  const supportedPrefix = ref.startsWith("page:")
    ? "page:"
    : ref.startsWith("source:")
      ? "source:"
      : "";
  if (!supportedPrefix) return null;
  const pageId = ref.slice(supportedPrefix.length).trim();
  return pageId || null;
}

export function firstTemporalPageId(event: TemporalEvent): string | null {
  for (const ref of [...event.subject_refs, ...event.source_refs, ...event.evidence_refs]) {
    const pageId = pageIdFromTemporalRef(ref);
    if (pageId) return pageId;
  }
  return null;
}

export function temporalDisplayEntries(value: Record<string, unknown>): [string, string][] {
  return Object.entries(value)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => [
      key,
      typeof item === "string" || typeof item === "number" || typeof item === "boolean"
        ? String(item)
        : JSON.stringify(item)
    ]);
}
