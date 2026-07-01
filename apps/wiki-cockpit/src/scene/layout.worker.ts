import { computeGalaxyLayout } from "./layout";
import type { GraphNode } from "../types";

type LayoutRequest = { nodes: GraphNode[]; maxNodes: number; snapshotAt?: string };

const workerSelf = globalThis as unknown as {
  onmessage: ((event: MessageEvent<LayoutRequest>) => void) | null;
  postMessage: (message: unknown) => void;
};

workerSelf.onmessage = (event: MessageEvent<LayoutRequest>) => {
  const { nodes, maxNodes, snapshotAt } = event.data;
  workerSelf.postMessage(computeGalaxyLayout(nodes, maxNodes, snapshotAt));
};

export {};
