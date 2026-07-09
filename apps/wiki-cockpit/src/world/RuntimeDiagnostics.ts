import type { RuntimeEvent, WorldState } from "./contracts";

export type DiagnosticRecord = { at: string; event: RuntimeEvent["type"]; centerId: string; view: string; detail: string };

const SECRET = /(token|password|cookie|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+/gi;

export class RuntimeDiagnostics {
  readonly #limit: number;
  readonly #records: DiagnosticRecord[] = [];

  constructor(limit = 200) {
    this.#limit = Math.max(1, limit);
  }

  record(event: RuntimeEvent, state: WorldState): void {
    const detail = JSON.stringify(event).replace(SECRET, "$1=[redacted]").slice(0, 500);
    this.#records.push({ at: new Date().toISOString(), event: event.type, centerId: state.centerId, view: state.view, detail });
    if (this.#records.length > this.#limit) this.#records.splice(0, this.#records.length - this.#limit);
  }

  records(): readonly DiagnosticRecord[] {
    return this.#records;
  }
}
