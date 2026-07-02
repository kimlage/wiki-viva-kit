import { computeWorldLayout } from "./perspectives";
import type { WorldRequest } from "./perspectives";

const workerSelf = globalThis as unknown as {
  onmessage: ((event: MessageEvent<WorldRequest & { requestId?: number }>) => void) | null;
  postMessage: (message: unknown) => void;
};

workerSelf.onmessage = (event: MessageEvent<WorldRequest & { requestId?: number }>) => {
  const { requestId, ...request } = event.data;
  workerSelf.postMessage({ requestId, layout: computeWorldLayout(request) });
};

export {};
