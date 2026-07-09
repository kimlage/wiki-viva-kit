export type ResourceResult<T> = { status: "committed"; value: T } | { status: "stale" | "aborted" };

export class ResourceController {
  readonly #controllers = new Map<string, AbortController>();
  readonly #revisions = new Map<string, number>();

  async run<T>(key: string, loader: (signal: AbortSignal) => Promise<T>): Promise<ResourceResult<T>> {
    this.abort(key);
    const controller = new AbortController();
    const revision = (this.#revisions.get(key) ?? 0) + 1;
    this.#revisions.set(key, revision);
    this.#controllers.set(key, controller);
    try {
      const value = await loader(controller.signal);
      if (controller.signal.aborted) return { status: "aborted" };
      if (this.#revisions.get(key) !== revision) return { status: "stale" };
      return { status: "committed", value };
    } catch (error) {
      if (controller.signal.aborted || (error instanceof DOMException && error.name === "AbortError")) return { status: "aborted" };
      throw error;
    } finally {
      if (this.#revisions.get(key) === revision) this.#controllers.delete(key);
    }
  }

  abort(key: string): void {
    this.#controllers.get(key)?.abort();
    this.#controllers.delete(key);
  }

  abortAll(): void {
    [...this.#controllers.keys()].forEach((key) => this.abort(key));
  }
}
