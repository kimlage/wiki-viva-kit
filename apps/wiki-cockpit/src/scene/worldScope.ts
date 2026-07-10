import type { GraphEdge, GraphNode } from "../types";

export type SceneGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

// A compiled anchor is an authoritative subworld. Once the compiler emits a
// quadrant_assignments object, even an empty one, the scene must not repopulate
// that subworld from global page-type fallback homes. Keep the active center
// plus the exact compiled members and induce only relations internal to that
// scope. A missing assignments object identifies a legacy/bare snapshot, where
// preserving the full graph and its deterministic fallback remains intentional.
export function scopeGraphToCompiledAnchor<T extends SceneGraph>(
  graph: T,
  centerId: string | null | undefined,
  assignments: Record<string, string[]> | undefined
): T {
  if (!centerId || assignments === undefined) return graph;

  const requestedIds = new Set<string>([centerId]);
  Object.values(assignments).forEach((memberIds) => {
    memberIds.forEach((memberId) => requestedIds.add(memberId));
  });

  const nodes = graph.nodes.filter((node) => requestedIds.has(node.id));
  const retainedIds = new Set(nodes.map((node) => node.id));
  const edges = graph.edges.filter(
    (edge) => retainedIds.has(edge.source) && retainedIds.has(edge.target)
  );
  return { ...graph, nodes, edges };
}
