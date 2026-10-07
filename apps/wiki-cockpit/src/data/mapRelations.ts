/** Human copy is localized in the existing UI catalogs; unknown types stay
 * explicitly unknown, with their exact vocabulary available in the record. */
export const MAP_RELATION_TYPES = new Set([
  "moc_parent", "source_ref", "markdown_link", "collection_member",
  "temporal_sequence", "impact", "proposal_transition", "participation", "source_emission"
]);
