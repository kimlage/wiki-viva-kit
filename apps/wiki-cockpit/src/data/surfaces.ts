// The interface COMPOSED by the stack — the one place that answers "which
// instruments exist in this world right now, and why". Every scope surface
// (create, intake, missions, views, sources) exists only when a block provides
// it; the laws (approve/health) arrive with the root; an empty world has no
// instruments at all. This is what makes the genesis tutorial honest: stages
// differ only by data, and the interface materializes because THIS module reads
// the stack — not because tutorial code toggles panels.

import type { AnchorRecord, SnapshotBundle } from "../types";
import type { DockId, PerspectiveId } from "../router";
import { PERSPECTIVES } from "../router";

export type Instruments = {
  worldEmpty: boolean;
  rootAnchorId: string | null;
  searchEnabled: boolean;
  // Command-bar destinations, in display order.
  destinations: Exclude<DockId, "">[];
  // The gamification package (missions + weather + karma) on the ROOT stack.
  missionsEnabled: boolean;
  missionProviders: string[];
  conditionEnabled: boolean;
  // Views: which perspectives this world offers and which is home.
  perspectives: PerspectiveId[];
  defaultPerspective: PerspectiveId;
  hasQuadrants: boolean;
  // Create/intake config from the root anchor (scope refinement happens per
  // focused anchor in the docks themselves).
  createArrangement: string;
  createCatalog: string[];
  intakeForms: string[];
};

const BARE: Instruments = {
  worldEmpty: true,
  rootAnchorId: null,
  searchEnabled: false,
  destinations: [],
  missionsEnabled: false,
  missionProviders: [],
  conditionEnabled: false,
  perspectives: ["radar"],
  defaultPerspective: "radar",
  hasQuadrants: false,
  createArrangement: "by_family",
  createCatalog: [],
  intakeForms: []
};

export function rootAnchor(bundle: SnapshotBundle): { id: string; record: AnchorRecord } | null {
  const anchors = bundle.blockStacks?.anchors ?? {};
  const pages = bundle.pages?.pages ?? [];
  const roots = pages.filter((page) => page.page_type === "root_entity" && anchors[page.id]);
  const rootPage =
    roots.find((page) => !page.moc_parent) ??
    roots.sort((a, b) => a.path.length - b.path.length || a.id.localeCompare(b.id))[0];
  if (rootPage) return { id: rootPage.id, record: anchors[rootPage.id] };
  const first = Object.keys(anchors).sort()[0];
  return first ? { id: first, record: anchors[first] } : null;
}

export function composeInstruments(bundle: SnapshotBundle): Instruments {
  const pages = bundle.pages?.pages ?? [];
  if (pages.length === 0) return { ...BARE };

  const root = rootAnchor(bundle);
  const ui = root?.record.interface;
  const stackIds = new Set((root?.record.stack ?? []).map((entry) => entry.id));

  const missionsEnabled = Boolean(ui?.missions?.active ?? stackIds.has("wiki.block.ui_missions.v1"));
  const hasQuadrants = Boolean(ui?.has_quadrants);

  // Perspectives: the stack's available set, intersected with what the code
  // ships. `focus` is reachable only with a locked page but stays listed.
  const available = (ui?.views?.available ?? [...PERSPECTIVES]).filter((view): view is PerspectiveId =>
    (PERSPECTIVES as readonly string[]).includes(view)
  );
  const perspectives = available.length > 0 ? available : (["radar"] as PerspectiveId[]);
  let defaultPerspective = (ui?.views?.default ?? "radar") as PerspectiveId;
  if (!perspectives.includes(defaultPerspective)) defaultPerspective = perspectives[0];

  const createEnabled = stackIds.has("wiki.block.ui_create.v1");
  const intakeForms = ui?.intake?.forms ?? [];
  const hasSources = pages.some((page) => String(page.page_type).startsWith("source"));

  const destinations: Exclude<DockId, "">[] = [];
  destinations.push("approve"); // the law arrives with the root
  if (intakeForms.length > 0) destinations.push("intake");
  if (createEnabled) destinations.push("create");
  if (root) destinations.push("blocks");
  if (hasSources || intakeForms.includes("source_sync")) destinations.push("source");
  destinations.push("gates"); // verification is law-tier, like approve

  return {
    worldEmpty: false,
    rootAnchorId: root?.id ?? null,
    searchEnabled: true,
    destinations,
    missionsEnabled,
    missionProviders: ui?.missions?.providers ?? [],
    conditionEnabled: missionsEnabled,
    perspectives,
    defaultPerspective,
    hasQuadrants,
    createArrangement: ui?.create?.arrangement ?? (hasQuadrants ? "by_quadrant" : "by_family"),
    createCatalog: ui?.create?.catalog ?? [],
    intakeForms
  };
}
