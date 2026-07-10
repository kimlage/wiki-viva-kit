// Presentation registry: how page types, contexts and trust states are shown.
// Every implementation can override labels, accents and 3D shapes through
// `wiki-cockpit.config.json` (`page_types`, `contexts`, `trust_colors`) without
// forking the cockpit, keeping the UI modular per deployment.

import { t, uiLanguage } from "./i18n";

export type NodeShape = "sphere" | "hub" | "crystal" | "diamond" | "comet" | "slab" | "spark" | "totem";

export type PageTypeStyle = {
  label: string;
  family: string;
  shape: NodeShape;
  accent: string;
};

export type ContextStyle = {
  label: string;
  accent: string;
};

export type TrustColors = {
  fresh: string;
  stale: string;
  unknown: string;
  proposal: string;
  root: string;
  risk: string;
};

export type PresentationOverrides = {
  page_types?: Record<string, Partial<PageTypeStyle>>;
  contexts?: Record<string, Partial<ContextStyle>>;
  trust_colors?: Partial<TrustColors>;
};

const FAMILY_STYLE: Record<string, { shape: NodeShape; accent: string }> = {
  root: { shape: "sphere", accent: "#6bd7ff" },
  hub: { shape: "hub", accent: "#7fd0e8" },
  content: { shape: "sphere", accent: "#9fb6c6" },
  source: { shape: "crystal", accent: "#57d9a0" },
  decision: { shape: "diamond", accent: "#e8c268" },
  action: { shape: "comet", accent: "#ff9c54" },
  rule: { shape: "slab", accent: "#8fa3ff" },
  event: { shape: "spark", accent: "#d989ff" },
  person: { shape: "totem", accent: "#ffb3c1" }
};

function style(family: string, label: string): PageTypeStyle {
  const base = FAMILY_STYLE[family] || FAMILY_STYLE.content;
  return { label, family, shape: base.shape, accent: base.accent };
}

const DEFAULT_PAGE_TYPES: Record<string, PageTypeStyle> = {
  root_index: style("root", "home overview"),
  root_entity: style("root", "root entity"),
  context_hub: style("hub", "area overview"),
  ontology_index: style("hub", "ontology index"),
  source_catalog: style("hub", "source library"),
  relationship_map: style("hub", "relationship map"),
  source: style("source", "evidence source"),
  evidence: style("source", "evidence record"),
  source_config: style("source", "source rules"),
  source_registry: style("source", "source registry"),
  input_channel: style("source", "input channel"),
  input_stage: style("source", "intake page"),
  decision: style("decision", "decision"),
  claim: style("decision", "claim"),
  action: style("action", "task"),
  process: style("action", "process"),
  operational_rule: style("rule", "operating guide"),
  dashboard: style("rule", "dashboard"),
  system_log: style("rule", "system log"),
  methodology_plan: style("rule", "method plan"),
  ingestion_event: style("event", "ingestion event"),
  journal_entry: style("event", "journal entry"),
  meeting: style("event", "meeting"),
  person: style("person", "person"),
  role: style("person", "role"),
  responsibility: style("person", "responsibility"),
  holon: style("content", "holon"),
  project: style("content", "project"),
  artifact: style("content", "artifact"),
  context_note: style("content", "context note"),
  perspective: style("rule", "reading lens"),
  proposal: style("event", "review draft"),
  visual_group: style("hub", "group"),
  visual_group_region: style("hub", "region group"),
  visual_group_source: style("source", "sources & evidence"),
  visual_group_hub: style("hub", "areas & workspaces"),
  visual_group_decision: style("decision", "decisions and claims"),
  visual_group_action: style("action", "actions & workflows"),
  visual_group_rule: style("rule", "rules & governance"),
  visual_group_event: style("event", "ingestion events"),
  visual_group_person: style("person", "people & responsibilities"),
  visual_group_content: style("content", "tools in this world"),
  visual_group_root: style("root", "independent worlds")
};

// Portuguese labels for the built-in page types. Config `page_types` overrides
// still win; this only gives pt wikis translated defaults instead of English.
const PT_PAGE_TYPE_LABELS: Record<string, string> = {
  root_index: "visão geral inicial",
  root_entity: "entidade raiz",
  context_hub: "visão da área",
  ontology_index: "índice de ontologia",
  source_catalog: "biblioteca de fontes",
  relationship_map: "mapa de relações",
  source: "fonte de evidência",
  evidence: "registro de evidência",
  source_config: "regras da fonte",
  source_registry: "registro de fontes",
  input_channel: "canal de entrada",
  input_stage: "página de entrada",
  decision: "decisão",
  claim: "afirmação",
  action: "tarefa",
  process: "processo",
  operational_rule: "guia operacional",
  dashboard: "painel",
  system_log: "registro do sistema",
  methodology_plan: "plano de método",
  ingestion_event: "evento de ingestão",
  journal_entry: "entrada de diário",
  meeting: "reunião",
  person: "pessoa",
  role: "papel",
  responsibility: "responsabilidade",
  holon: "holon",
  project: "projeto",
  artifact: "artefato",
  context_note: "nota de contexto",
  perspective: "lente de leitura",
  proposal: "rascunho de revisão",
  visual_group: "grupo",
  visual_group_region: "grupo de região",
  visual_group_source: "fontes & evidências",
  visual_group_hub: "áreas & espaços de trabalho",
  visual_group_decision: "decisões e claims",
  visual_group_action: "ações & fluxos",
  visual_group_rule: "regras & governança",
  visual_group_event: "eventos de ingestão",
  visual_group_person: "pessoas & responsabilidades",
  visual_group_content: "ferramentas deste mundo",
  visual_group_root: "mundos independentes"
};

const DEFAULT_TRUST_COLORS: TrustColors = {
  fresh: "#5ee6a8",
  stale: "#ffb454",
  unknown: "#9aa3b2",
  proposal: "#c57cff",
  root: "#6bd7ff",
  risk: "#ff7a8a"
};

// Context identity palette: 12 slots = 6 hue anchors × 2 lightness tiers,
// sampled on the blue↔yellow axis dichromats retain (OKLCH hues 255/210/165/
// 110/45/335, tiers L≈0.70 C≈0.115 and L≈0.82 C≈0.09), interleaved so early
// assignments maximize hue separation. Deliberately AVOIDS the reserved state
// accents: amber #ffb454 (needs refresh), purple #c57cff (draft/approval),
// search cyan #79e6ff, risk red #ff7a8a — a context must never impersonate a
// state. Guarded by the CVD-simulation test in presentation.test.ts.
const CONTEXT_ACCENTS = [
  "#6ca1e5", // blue A
  "#d98660", // salmon A
  "#4cb58c", // teal A
  "#ca82bb", // pink A
  "#b6b857", // lime A (L 0.76 — lifted for deutan separation from salmon A)
  "#22b1c6", // cyan A
  "#9dc7fe", // blue B (lighter tier)
  "#f6b294", // salmon B
  "#8ad7b6", // teal B
  "#e9aedb", // pink B
  "#c7ca85", // lime B
  "#79d4e4" // cyan B
];

let pageTypeOverrides: Record<string, Partial<PageTypeStyle>> = {};
let contextOverrides: Record<string, Partial<ContextStyle>> = {};
let trustColors: TrustColors = { ...DEFAULT_TRUST_COLORS };
// Deterministic slot registry: sorted context names → palette slots, refreshed
// per snapshot. Hash assignment only remains as a fallback for contexts that
// were never registered (it collides once contexts outnumber slots).
let contextSlots: Map<string, number> = new Map();

export function configurePresentation(overrides: PresentationOverrides | null | undefined): void {
  pageTypeOverrides = overrides?.page_types || {};
  contextOverrides = overrides?.contexts || {};
  trustColors = { ...DEFAULT_TRUST_COLORS, ...(overrides?.trust_colors || {}) };
}

// Called once per snapshot load with EVERY context in the wiki: sorted names
// get distinct palette slots (up to 12), so 8 contexts never collide the way
// hash assignment can. Sorted order keeps the mapping stable across sessions
// for a given wiki; per-context `contexts.<name>.accent` overrides still win.
export function registerContextPalette(contexts: string[]): void {
  const sorted = [...new Set(contexts.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  contextSlots = new Map(sorted.map((name, index) => [name, index % CONTEXT_ACCENTS.length]));
}

export function pageTypeStyle(pageType: string): PageTypeStyle {
  const base = DEFAULT_PAGE_TYPES[pageType] || style("content", (pageType || "content").replaceAll("_", " "));
  const localizedLabel = uiLanguage() === "pt" ? PT_PAGE_TYPE_LABELS[pageType] || base.label : base.label;
  const override = pageTypeOverrides[pageType];
  if (!override) return { ...base, label: localizedLabel };
  return {
    label: override.label || localizedLabel,
    family: override.family || base.family,
    shape: override.shape || base.shape,
    accent: override.accent || base.accent
  };
}

export function pageTypeLabel(pageType: string): string {
  return pageTypeStyle(pageType).label;
}

export function contextStyle(context: string): ContextStyle {
  const name = context || "system";
  const override = contextOverrides[name];
  const slot = contextSlots.get(name);
  const hash = [...name].reduce((total, char) => (total * 31 + char.charCodeAt(0)) % 997, 7);
  return {
    label: override?.label || name,
    accent: override?.accent || CONTEXT_ACCENTS[slot ?? hash % CONTEXT_ACCENTS.length]
  };
}

export function contextLabel(context: string): string {
  return contextStyle(context).label;
}

export function trustColor(state: keyof TrustColors): string {
  return trustColors[state];
}

// ---------------------------------------------------------------------------
// Aging: hue = WHO a node is (context); tone = HOW it is (state). The state
// tones are normalized to fixed OKLCH lightness bands so "darker = staler"
// holds ACROSS contexts (a fresh purple must never be as dark as a stale
// cyan) — the one channel color-blind users can always trust. Ordering:
// proposal-bleach (≈0.82) > fresh-calm (≈0.58) > stale-aged (≈0.46) >
// unknown-veil (≈0.35). Stale BRIGHTNESS comes from the amber emissive/glow
// annotation, not the body. Invariants pinned in presentation.test.ts.

type Oklch = { l: number; c: number; h: number };

function srgbChannelToLinear(value: number): number {
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}
function linearChannelToSrgb(value: number): number {
  const clamped = Math.max(0, Math.min(1, value));
  return clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * clamped ** (1 / 2.4) - 0.055;
}

export function hexToOklch(hex: string): Oklch {
  const int = parseInt(hex.slice(1), 16);
  const r = srgbChannelToLinear(((int >> 16) & 255) / 255);
  const g = srgbChannelToLinear(((int >> 8) & 255) / 255);
  const b = srgbChannelToLinear((int & 255) / 255);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const c = Math.hypot(a, bb);
  const h = ((Math.atan2(bb, a) * 180) / Math.PI + 360) % 360;
  return { l: L, c, h };
}

export function oklchToHex({ l, c, h }: Oklch): string {
  const rad = (h * Math.PI) / 180;
  const a = c * Math.cos(rad);
  const bb = c * Math.sin(rad);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * bb) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * bb) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * bb) ** 3;
  const r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_;
  const g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_;
  const b = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_;
  const toByte = (channel: number) => Math.round(linearChannelToSrgb(channel) * 255);
  return `#${[r, g, b].map((ch) => toByte(ch).toString(16).padStart(2, "0")).join("")}`;
}

// Fixed lightness bands per state (see the invariant comment above).
const STATE_BANDS: Record<TrustKeyName, { l: number; maxC: number; minC: number }> = {
  fresh: { l: 0.58, maxC: 0.085, minC: 0 },
  stale: { l: 0.46, maxC: 0.075, minC: 0 },
  unknown: { l: 0.35, maxC: 0.03, minC: 0 },
  proposal: { l: 0.82, maxC: 0.09, minC: 0.045 }
};

export type TrustKeyName = "fresh" | "stale" | "unknown" | "proposal";

export function agedColor(accentHex: string, state: TrustKeyName): string {
  const { c, h } = hexToOklch(accentHex);
  const band = STATE_BANDS[state];
  // Stale drifts slightly warm (aged/umber character) without entering the
  // reserved amber zone; the band clamp does the heavy lifting.
  const hue = state === "stale" ? h + (h > 90 && h < 270 ? -12 : 12) : h;
  const chroma = Math.max(band.minC, Math.min(state === "unknown" ? c * 0.25 : c, band.maxC));
  return oklchToHex({ l: band.l, c: chroma, h: ((hue % 360) + 360) % 360 });
}

export type EdgeStyle = { label: string; color: string };

const EDGE_STYLES: Record<string, EdgeStyle> = {
  moc_parent: { label: "navigation", color: "#4f8fb5" },
  collection_member: { label: "collection", color: "#70a9cc" },
  source_ref: { label: "evidence", color: "#57d9a0" },
  markdown_link: { label: "reference", color: "#5a6a76" },
  pr_impact: { label: "review impact", color: "#c57cff" },
  ingestion_chain: { label: "ingestion", color: "#ff9c54" }
};

export function edgeStyle(type: string): EdgeStyle {
  return EDGE_STYLES[type] || { label: (type || "link").replaceAll("_", " "), color: "#5a6a76" };
}

// Labels for world groups (perspective sectors). Every user-facing label
// flows through the registry + i18n — raw slugs never reach the screen.
export function worldGroupLabel(kind: string, labelKey: string): string {
  if (kind === "context") return contextLabel(labelKey);
  if (kind === "page_type") return pageTypeLabel(labelKey);
  if (kind === "attention") return labelKey === "atencao" ? t("group.attention") : pageTypeLabel(labelKey);
  if (kind === "orphan") return t("group.orphan");
  if (kind === "relation") return t(`relation.${labelKey}`);
  if (kind === "facet" || kind === "quadrant") return t(`facet.${labelKey}`);
  if (kind === "family" || kind === "region_family") return pageTypeLabel(`visual_group_${labelKey}`);
  if (kind === "source_flow") return t(`source.flow.${labelKey}`);
  if (kind === "work_queue") return t(`work.queue.${labelKey}`);
  if (kind === "core") return t("quadrant.core");
  return labelKey;
}

export function worldGroupDescription(kind: string, labelKey: string): string {
  if (kind === "family" || kind === "region_family") return t(`group.family.${labelKey}.description`);
  if (kind === "source_flow") return t(`group.source_flow.${labelKey}.description`);
  return "";
}

export function perspectiveLabel(perspective: string): { label: string; hint: string; glyph: string } {
  const glyphs: Record<string, string> = { radar: "◎", atlas: "🜨", districts: "⬡", trails: "⇢", focus: "✦", center: "⌾", quadrants: "田", sources: "▣", work: "✓" };
  return {
    label: t(`perspective.${perspective}`),
    hint: t(`perspective.${perspective}.hint`),
    glyph: glyphs[perspective] || "◎"
  };
}

// Raw-data layer: untreated inputs (source records, intake pages, ingestion
// events) — evidence, not conclusions. Rendered distinctly so the raw layer is
// identifiable at a glance in every surface.
const RAW_TYPES = new Set(["ingestion_event", "input_stage", "input_channel"]);

export function isRawData(pageType: string): boolean {
  if (RAW_TYPES.has(pageType)) return true;
  return pageTypeStyle(pageType).family === "source";
}

// META layer: pages that DEFINE the system — molds, not content. Blueprints in
// the scene (wireframe), a mold banner in the reader, a meta chip in lists.
// You never confuse the blueprint with the building. Same precedent as the raw
// layer: a rendering LAYER, not a new color (CVD-safe by construction).
const META_TYPES = new Set(["template_block", "skill", "perspective"]);

export function isMetaPage(pageType: string): boolean {
  return META_TYPES.has(pageType);
}

// The landmark GLYPH per identity landmark — the 2D face of the anchor's
// architecture (reader banner, block dock chips, breadcrumbs).
const LANDMARK_GLYPHS: Record<string, string> = {
  observatory: "✦",
  beacon: "▲",
  crystal_spire: "◆",
  plaza: "▦",
  forge: "⚒",
  shelf: "≣",
  engine: "⚙"
};

export function landmarkGlyph(landmark: string): string {
  return LANDMARK_GLYPHS[landmark] || "◈";
}
