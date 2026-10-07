/** Human copy is localized in the existing UI catalogs; unknown types stay
 * explicitly unknown, with their exact vocabulary available in the record. */
export const MAP_RELATION_TYPES = new Set([
  "moc_parent", "source_ref", "markdown_link", "collection_member",
  "temporal_sequence", "impact", "proposal_transition", "participation", "source_emission"
]);

/** Presentation only: names, stroke and color distinguish recorded types.
 * Direction still comes from each original edge, never from its type. */
const RELATION_STYLES: Record<string,{key:string;color:string;dash:string}> = {
  moc_parent: {key:"hierarchy",color:"var(--wiki-text-muted)",dash:"5 5"},
  source_ref: {key:"source",color:"var(--wiki-accent)",dash:"none"},
  source_emission: {key:"emission",color:"var(--wiki-accent-strong)",dash:"10 3 2 3"},
  impact: {key:"impact",color:"var(--wiki-focus)",dash:"8 3"},
  markdown_link: {key:"reference",color:"var(--wiki-text-muted)",dash:"2 4"},
  collection_member: {key:"collection",color:"var(--wiki-accent-strong)",dash:"6 2 1 2"},
  temporal_sequence: {key:"sequence",color:"var(--wiki-text)",dash:"12 3"},
  participation: {key:"participation",color:"var(--wiki-accent)",dash:"3 3"},
  proposal_transition: {key:"proposal",color:"var(--wiki-focus)",dash:"10 2 2 2 2 2"}
};
const UNKNOWN_RELATION_STYLE={key:"unknown",color:"var(--wiki-text-muted)",dash:"1 5"};
export const mapRelationStyle=(type:string)=>Object.prototype.hasOwnProperty.call(RELATION_STYLES,type)?RELATION_STYLES[type]:UNKNOWN_RELATION_STYLE;
