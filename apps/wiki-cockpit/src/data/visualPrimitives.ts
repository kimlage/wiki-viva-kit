import type { AnchorRecord, RegionGroupPayload } from "../types";

export const VISUAL_PRIMITIVES = [
  "region_card",
  "region_work_card",
  "attention_rail",
  "type_shelf",
  "source_badge",
  "action_lane",
  "risk_notch",
  "review_halo",
  "hidden_histogram",
  "core_debt_meter",
  "empty_region_affordance",
  "bridge_count",
  "center_badge",
  "scope_chip",
  "legend_key"
] as const;

export const VISUAL_SLOTS = [
  "region.card",
  "region.rail",
  "region.shelf",
  "region.marker",
  "region.empty",
  "cluster.tooltip",
  "fallback.card",
  "reader.badge",
  "dock.action",
  "legend.entry"
] as const;

export const VISUAL_PACKS = ["region_operations", "evidence_first", "review_first", "quiet_structure"] as const;

export type VisualPrimitiveId = (typeof VISUAL_PRIMITIVES)[number];
export type VisualSlotId = (typeof VISUAL_SLOTS)[number];
export type VisualPackId = (typeof VISUAL_PACKS)[number];

export type VisualPrimitiveDefinition = {
  id: VisualPrimitiveId;
  purpose: string;
  slots: VisualSlotId[];
  data: string[];
};

export const PRIMITIVE_DEFINITIONS: Record<VisualPrimitiveId, VisualPrimitiveDefinition> = {
  region_card: {
    id: "region_card",
    purpose: "Summarize region size and purpose.",
    slots: ["region.card"],
    data: ["summary.total", "summary.shown", "summary.hidden", "purpose"]
  },
  region_work_card: {
    id: "region_work_card",
    purpose: "Show composition, attention and next actions.",
    slots: ["fallback.card", "region.card"],
    data: ["type_mix", "attention_hints", "action_hints"]
  },
  attention_rail: {
    id: "attention_rail",
    purpose: "Filter attention inside the active region.",
    slots: ["region.rail"],
    data: ["attention_hints"]
  },
  type_shelf: {
    id: "type_shelf",
    purpose: "Show why a region is dense by page family.",
    slots: ["region.shelf"],
    data: ["type_mix"]
  },
  source_badge: {
    id: "source_badge",
    purpose: "Mark raw, synced and consolidated evidence.",
    slots: ["reader.badge"],
    data: ["summary.raw", "summary.source_backed"]
  },
  action_lane: {
    id: "action_lane",
    purpose: "Separate work items from context.",
    slots: ["region.marker", "dock.action"],
    data: ["summary.open_actions", "action_hints"]
  },
  risk_notch: {
    id: "risk_notch",
    purpose: "Show risk without flooding the region.",
    slots: ["region.marker"],
    data: ["summary.risk"]
  },
  review_halo: {
    id: "review_halo",
    purpose: "Show pending proposal or approval review.",
    slots: ["region.marker", "dock.action"],
    data: ["summary.proposal"]
  },
  hidden_histogram: {
    id: "hidden_histogram",
    purpose: "Describe hidden work behind render limits.",
    slots: ["cluster.tooltip"],
    data: ["summary.hidden"]
  },
  core_debt_meter: {
    id: "core_debt_meter",
    purpose: "Flag classification debt in the core ring.",
    slots: ["region.rail"],
    data: ["summary.total", "visual_role"]
  },
  empty_region_affordance: {
    id: "empty_region_affordance",
    purpose: "Explain required absences and valid creation paths.",
    slots: ["region.empty"],
    data: ["summary.total", "action_hints"]
  },
  bridge_count: {
    id: "bridge_count",
    purpose: "Explain cross-region dependencies.",
    slots: ["region.marker"],
    data: ["edges"]
  },
  center_badge: {
    id: "center_badge",
    purpose: "Show the active anchor center.",
    slots: ["region.card"],
    data: ["anchor"]
  },
  scope_chip: {
    id: "scope_chip",
    purpose: "Show the active center, region or filter scope.",
    slots: ["region.marker"],
    data: ["center", "region"]
  },
  legend_key: {
    id: "legend_key",
    purpose: "Explain the resolved visual grammar.",
    slots: ["legend.entry"],
    data: ["visual_grammar"]
  }
};

export const DEFAULT_SLOT_PRIMITIVES: Record<VisualSlotId, VisualPrimitiveId> = {
  "region.card": "region_card",
  "region.rail": "attention_rail",
  "region.shelf": "type_shelf",
  "region.marker": "action_lane",
  "region.empty": "empty_region_affordance",
  "cluster.tooltip": "hidden_histogram",
  "fallback.card": "region_work_card",
  "reader.badge": "source_badge",
  "dock.action": "action_lane",
  "legend.entry": "legend_key"
};

function isPrimitive(value: string): value is VisualPrimitiveId {
  return (VISUAL_PRIMITIVES as readonly string[]).includes(value);
}

function isSlot(value: string): value is VisualSlotId {
  return (VISUAL_SLOTS as readonly string[]).includes(value);
}

export function regionPayloadByKey(record: AnchorRecord | null | undefined): Map<string, RegionGroupPayload> {
  const map = new Map<string, RegionGroupPayload>();
  for (const region of record?.derived.region_groups?.groups ?? []) {
    map.set(region.label_key, region);
    map.set(region.id, region);
    if (region.kind === "core") map.set("__core__", region);
  }
  return map;
}

export function resolvePrimitiveForSlot(
  record: AnchorRecord | null | undefined,
  region: RegionGroupPayload | null | undefined,
  slot: VisualSlotId
): VisualPrimitiveDefinition {
  const packId = region?.visual.pack_id || record?.visual_grammar?.default_pack || "region_operations";
  const primitiveId = region?.visual.slots?.[slot] || record?.visual_grammar?.packs?.[packId]?.slots?.[slot] || DEFAULT_SLOT_PRIMITIVES[slot];
  const safeId: VisualPrimitiveId = isPrimitive(String(primitiveId)) ? (primitiveId as VisualPrimitiveId) : DEFAULT_SLOT_PRIMITIVES[slot];
  return PRIMITIVE_DEFINITIONS[safeId];
}

export function resolvedPrimitiveDiagnostics(record: AnchorRecord | null | undefined): { slot: VisualSlotId; primitive: VisualPrimitiveId; purpose: string }[] {
  const grammar = record?.visual_grammar;
  const packId = grammar?.default_pack || "region_operations";
  const slots = grammar?.packs?.[packId]?.slots ?? {};
  return VISUAL_SLOTS.map((slot) => {
    const primitive = slots[slot] && isPrimitive(slots[slot]) ? slots[slot] : DEFAULT_SLOT_PRIMITIVES[slot];
    return { slot, primitive, purpose: PRIMITIVE_DEFINITIONS[primitive].purpose };
  });
}

export function primitiveSlotClass(region: RegionGroupPayload | null | undefined, slot: string): string {
  if (!isSlot(slot)) return "visual-unknown";
  const primitive = region?.visual.slots?.[slot] || DEFAULT_SLOT_PRIMITIVES[slot];
  return `visual-${isPrimitive(String(primitive)) ? primitive : DEFAULT_SLOT_PRIMITIVES[slot]}`;
}
