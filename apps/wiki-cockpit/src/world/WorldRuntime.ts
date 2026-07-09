import type { PageEntityIndex, RuntimeEvent, WorldState } from "./contracts";
import { createDefaultKernel, type RegistryKernel } from "./registries/RegistryKernel";
import { createWorldReducer } from "./state/WorldReducer";
import { RuntimeDiagnostics } from "./RuntimeDiagnostics";

export type RuntimeListener = (state: WorldState, event: RuntimeEvent) => void;

export class WorldRuntime {
  readonly kernel: RegistryKernel;
  readonly pages: PageEntityIndex;
  readonly diagnostics: RuntimeDiagnostics;
  #state: WorldState;
  readonly #reduce: ReturnType<typeof createWorldReducer>;
  readonly #listeners = new Set<RuntimeListener>();

  constructor(options: { state: WorldState; pages: PageEntityIndex; kernel?: RegistryKernel; diagnostics?: RuntimeDiagnostics }) {
    this.kernel = options.kernel ?? createDefaultKernel();
    this.pages = options.pages;
    this.diagnostics = options.diagnostics ?? new RuntimeDiagnostics();
    this.#state = options.state;
    this.#reduce = createWorldReducer(this.pages, this.kernel);
    const errors = this.kernel.validateState(this.#state);
    if (errors.length) throw new Error(`Invalid initial world state: ${errors.join("; ")}`);
    // The legacy genesis tutorial has one pre-world stage with zero pages.
    // Compatibility mode may represent that void; native v8 snapshots must
    // always hydrate a real root page.
    if (this.pages.size === 0 && this.#state.mode !== "v8") return;
    if (!this.pages.has(this.#state.centerId)) throw new Error(`Invalid center '${this.#state.centerId}'`);
  }

  getState(): WorldState {
    return this.#state;
  }

  dispatch(event: RuntimeEvent): WorldState {
    if (!this.kernel.interactions.has(event.type)) throw new Error(`Unregistered runtime interaction '${event.type}'`);
    const next = this.#reduce(this.#state, event);
    this.diagnostics.record(event, next);
    if (next !== this.#state) {
      this.#state = next;
      this.#listeners.forEach((listener) => listener(next, event));
    }
    return this.#state;
  }

  subscribe(listener: RuntimeListener): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }
}
