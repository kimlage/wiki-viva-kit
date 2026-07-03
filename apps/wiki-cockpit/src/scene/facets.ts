// Facets in the scene — the frontend mirror of wiki_core/facets.py. The Focus
// perspective buckets a page's neighbors into the four lenses. Pure, so the
// layout worker can use it. Labels live in i18n (facet.*); this is only the
// bucketing.

export const SCENE_FACETS = ["intencao", "percepcao", "pratica", "relacoes"] as const;
export type SceneFacet = (typeof SCENE_FACETS)[number];

const PAGE_TYPE_FACET: Record<string, SceneFacet | null> = {
  decision: "intencao",
  operational_rule: "intencao",
  responsibility: "intencao",
  project: "intencao",
  initiative: "intencao",
  insight: "percepcao",
  journal_entry: "percepcao",
  claim: "percepcao",
  perspective: "percepcao",
  action: "pratica",
  process: "pratica",
  artifact: "pratica",
  evidence: "pratica",
  source: "pratica",
  source_config: "pratica",
  ingestion_event: "pratica",
  input_channel: "pratica",
  input_stage: "pratica",
  dashboard: "pratica",
  person: "relacoes",
  meeting: "relacoes",
  role: "relacoes",
  holon: "relacoes",
  relationship_map: "relacoes",
  root_entity: null,
  root_index: null,
  context_hub: null,
  ontology_index: null,
  source_registry: null,
  source_catalog: null,
  system_log: null
};

const EDGE_FACET: Record<string, SceneFacet | null> = {
  moc_parent: null,
  markdown_link: null,
  source_ref: "pratica",
  pr_impact: "pratica",
  ingestion_chain: "pratica",
  decision: "intencao",
  claim: "percepcao",
  action: "pratica"
};

// Which lens a neighbor falls under, seen from the center. page_type wins;
// the typed edge is the fallback; null = structural (shown outside the lenses).
export function sceneFacetOf(pageType: string | undefined, edgeType: string | undefined): SceneFacet | null {
  if (pageType && pageType in PAGE_TYPE_FACET) return PAGE_TYPE_FACET[pageType];
  if (edgeType && edgeType in EDGE_FACET) return EDGE_FACET[edgeType];
  return null;
}
