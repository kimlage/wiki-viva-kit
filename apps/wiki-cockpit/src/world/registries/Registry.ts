export type RegistryEntry = { id: string };

export class Registry<T extends RegistryEntry> {
  readonly #kind: string;
  readonly #entries = new Map<string, T>();

  constructor(kind: string) {
    this.#kind = kind;
  }

  register(entry: T): this {
    if (this.#entries.has(entry.id)) throw new Error(`${this.#kind} '${entry.id}' is already registered`);
    this.#entries.set(entry.id, Object.freeze({ ...entry }));
    return this;
  }

  get(id: string): T | undefined {
    return this.#entries.get(id);
  }

  require(id: string): T {
    const entry = this.get(id);
    if (!entry) throw new Error(`Unknown ${this.#kind} '${id}'`);
    return entry;
  }

  has(id: string): boolean {
    return this.#entries.has(id);
  }

  values(): T[] {
    return [...this.#entries.values()];
  }
}
