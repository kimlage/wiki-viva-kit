// Presentation registry: how page types, contexts and trust states are shown.
// Every implementation can override labels, accents and 3D shapes through
// `wiki-cockpit.config.json` (`page_types`, `contexts`, `trust_colors`) without
// forking the cockpit, keeping the UI modular per deployment.

export type NodeShape = "sphere" | "hub" | "crystal" | "diamond" | "comet" | "slab" | "spark";

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
  person: { shape: "sphere", accent: "#ffb3c1" }
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
  proposal: style("event", "review draft")
};

const DEFAULT_TRUST_COLORS: TrustColors = {
  fresh: "#5ee6a8",
  stale: "#ffb454",
  unknown: "#9aa3b2",
  proposal: "#c57cff",
  root: "#6bd7ff",
  risk: "#ff7a8a"
};

const CONTEXT_ACCENTS = ["#6bd7ff", "#ffb454", "#c57cff", "#5ee6a8", "#ff9c54", "#8fa3ff", "#ffb3c1", "#7fd0e8"];

let pageTypeOverrides: Record<string, Partial<PageTypeStyle>> = {};
let contextOverrides: Record<string, Partial<ContextStyle>> = {};
let trustColors: TrustColors = { ...DEFAULT_TRUST_COLORS };

export function configurePresentation(overrides: PresentationOverrides | null | undefined): void {
  pageTypeOverrides = overrides?.page_types || {};
  contextOverrides = overrides?.contexts || {};
  trustColors = { ...DEFAULT_TRUST_COLORS, ...(overrides?.trust_colors || {}) };
}

export function pageTypeStyle(pageType: string): PageTypeStyle {
  const base = DEFAULT_PAGE_TYPES[pageType] || style("content", (pageType || "content").replaceAll("_", " "));
  const override = pageTypeOverrides[pageType];
  if (!override) return base;
  return {
    label: override.label || base.label,
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
  const hash = [...name].reduce((total, char) => (total * 31 + char.charCodeAt(0)) % 997, 7);
  return {
    label: override?.label || name,
    accent: override?.accent || CONTEXT_ACCENTS[hash % CONTEXT_ACCENTS.length]
  };
}

export function contextLabel(context: string): string {
  return contextStyle(context).label;
}

export function trustColor(state: keyof TrustColors): string {
  return trustColors[state];
}

export type EdgeStyle = { label: string; color: string };

const EDGE_STYLES: Record<string, EdgeStyle> = {
  moc_parent: { label: "navigation", color: "#4f8fb5" },
  source_ref: { label: "evidence", color: "#57d9a0" },
  markdown_link: { label: "reference", color: "#5a6a76" },
  pr_impact: { label: "review impact", color: "#c57cff" },
  ingestion_chain: { label: "ingestion", color: "#ff9c54" }
};

export function edgeStyle(type: string): EdgeStyle {
  return EDGE_STYLES[type] || { label: (type || "link").replaceAll("_", " "), color: "#5a6a76" };
}
