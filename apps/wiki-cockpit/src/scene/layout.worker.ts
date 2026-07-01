import { computeGalaxyLayout } from "./layout";
import type { GraphNode } from "../types";

const workerSelf = globalThis as unknown as {
  onmessage: ((event: MessageEvent<{ nodes: GraphNode[]; maxNodes: number }>) => void) | null;
  postMessage: (message: unknown) => void;
};

workerSelf.onmessage = (event: MessageEvent<{ nodes: GraphNode[]; maxNodes: number }>) => {
  const { nodes, maxNodes } = event.data;
  workerSelf.postMessage(computeGalaxyLayout(nodes, maxNodes));
};

export {};
