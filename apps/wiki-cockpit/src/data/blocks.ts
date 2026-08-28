// Read model over the v2 block payloads (blocks.json + block_stacks.json). The
// cockpit stops asking only "what page_type is this?" and asks "what blocks are
// active here, from where, and what do they make of the scope?". Degrades to
// empty when a snapshot predates blocks (old wikis stay loadable).

import type { AnchorRecord, BlockDefinition, SnapshotBundle } from "../types";

export function anchorIds(bundle: SnapshotBundle): string[] {
  return Object.keys(bundle.blockStacks?.anchors ?? {}).sort();
}

export function isAnchor(bundle: SnapshotBundle, pageId: string | undefined): boolean {
  if (!pageId) return false;
  return Boolean(bundle.blockStacks?.anchors?.[pageId]);
}

export function anchorRecord(bundle: SnapshotBundle, pageId: string | undefined): AnchorRecord | null {
  if (!pageId) return null;
  return bundle.blockStacks?.anchors?.[pageId] ?? null;
}

export function anchorDeclaresBlock(record: AnchorRecord | null | undefined, blockId: string): boolean {
  return Boolean(
    record?.stack?.some((block) => block.id === blockId && (block.origin === "page" || block.origin.startsWith("template:")))
  );
}

export function anchorDeclaresQuadrants(record: AnchorRecord | null | undefined): boolean {
  return Boolean(record?.interface?.has_quadrants && anchorDeclaresBlock(record, "wiki.block.quadrants.v1"));
}

// A locally declared quadrant block is one way to own a quadrant world. The
// compiler may also materialize an inherited block into authoritative,
// anchor-relative assignments. Once that derived object exists (including an
// explicitly empty one), the center has a real quadrant projection and must
// not silently fall back to Focus while the navigator still says Quadrants.
export function anchorSupportsQuadrants(record: AnchorRecord | null | undefined): boolean {
  return Boolean(
    record?.interface?.has_quadrants &&
    (anchorDeclaresQuadrants(record) || record.derived?.quadrant_assignments !== undefined)
  );
}

export function blockDef(bundle: SnapshotBundle, blockId: string): BlockDefinition | null {
  return bundle.blocks?.blocks?.[blockId] ?? null;
}

// The anchor to X-ray for the current focus: the locked page if it is an anchor,
// else the nearest anchor up its moc_parent chain, else the first root anchor.
export function focusAnchorId(bundle: SnapshotBundle, pageId: string | undefined): string | null {
  if (pageId && isAnchor(bundle, pageId)) return pageId;
  // Walk moc_parent up until we hit an anchor.
  const pages = bundle.pages?.pages ?? [];
  const byId = new Map(pages.map((p) => [p.id, p]));
  const byPath = new Map(pages.map((p) => [p.path, p]));
  let current = pageId ? byId.get(pageId) : undefined;
  const seen = new Set<string>();
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    if (isAnchor(bundle, current.id)) return current.id;
    const parentKey = current.moc_parent;
    current = parentKey ? byPath.get(parentKey) ?? byId.get(parentKey) : undefined;
  }
  const anchors = anchorIds(bundle);
  // Prefer the WORLD's root: the root_entity with no moc_parent. Nested
  // root_entities (companies, products, people) keep their own subworlds, but
  // only hijack focus when selected or passed as ?center=.
  const rootPages = pages.filter((page) => page.page_type === "root_entity" && anchors.includes(page.id));
  const rootPage =
    rootPages.find((page) => !page.moc_parent) ??
    rootPages.sort((a, b) => a.path.length - b.path.length || a.id.localeCompare(b.id))[0];
  if (rootPage) return rootPage.id;
  const observatory = anchors.find((id) => (bundle.blockStacks?.anchors?.[id]?.identity?.landmark ?? "") === "observatory");
  return observatory ?? anchors[0] ?? null;
}

// A short, human origin label ("template", "root", "page", "system/context").
export function originLabel(origin: string): string {
  if (origin === "page") return "page";
  if (origin === "kit") return "kit";
  if (origin.startsWith("template:")) return "template";
  if (origin.startsWith("anchor:")) return "inherited";
  return origin;
}

export function originDetail(origin: string): string {
  const idx = origin.indexOf(":");
  return idx >= 0 ? origin.slice(idx + 1) : "";
}
