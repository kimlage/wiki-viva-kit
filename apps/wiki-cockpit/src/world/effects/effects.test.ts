import { describe, expect, it } from "vitest";
import { CommandBus } from "./CommandBus";
import { ResourceController } from "./ResourceController";

describe("runtime effects", () => {
  it("aborts stale reads when a new route requests the same resource", async () => {
    const resources = new ResourceController();
    let releaseFirst!: () => void;
    const first = resources.run("content", (signal) => new Promise<string>((resolve, reject) => {
      releaseFirst = () => resolve("old");
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const second = resources.run("content", async () => "new");
    releaseFirst();
    await expect(first).resolves.toEqual({ status: "aborted" });
    await expect(second).resolves.toEqual({ status: "committed", value: "new" });
  });

  it("deduplicates command submits and blocks publish outside the human gate", async () => {
    const bus = new CommandBus(["gates.run"]);
    const command = { id: "run-gates", capability: "gates.run", risk: "write" as const, preview: "Run deterministic gates", idempotencyKey: "gate-1" };
    let calls = 0;
    const execute = async () => { calls += 1; return "Gate receipt recorded"; };
    const [a, b] = await Promise.all([bus.execute(command, execute), bus.execute(command, execute)]);
    expect(calls).toBe(1);
    expect(a).toEqual(b);
    expect(() => bus.preview({ ...command, id: "merge", risk: "publish" })).toThrow(/human gate/);
  });
});
