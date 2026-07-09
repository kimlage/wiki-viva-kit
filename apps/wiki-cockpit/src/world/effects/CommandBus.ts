import type { CommandReceipt, OperatorCommand } from "../contracts";

export type CommandExecutor = (command: OperatorCommand, signal: AbortSignal) => Promise<string>;

export class CommandBus {
  readonly #capabilities: ReadonlySet<string>;
  readonly #inFlight = new Map<string, Promise<CommandReceipt>>();

  constructor(capabilities: Iterable<string>) {
    this.#capabilities = new Set(capabilities);
  }

  preview(command: OperatorCommand, now = new Date()): CommandReceipt {
    this.assertAllowed(command);
    return { commandId: command.id, status: "previewed", startedAt: now.toISOString(), redactedSummary: command.preview };
  }

  execute(command: OperatorCommand, executor: CommandExecutor, signal = new AbortController().signal): Promise<CommandReceipt> {
    this.assertAllowed(command);
    const key = command.idempotencyKey ?? command.id;
    const active = this.#inFlight.get(key);
    if (active) return active;
    const startedAt = new Date().toISOString();
    const task = executor(command, signal)
      .then((summary) => ({ commandId: command.id, status: "succeeded" as const, startedAt, finishedAt: new Date().toISOString(), redactedSummary: summary }))
      .catch((error: unknown) => ({
        commandId: command.id,
        status: signal.aborted ? ("cancelled" as const) : ("failed" as const),
        startedAt,
        finishedAt: new Date().toISOString(),
        redactedSummary: error instanceof Error ? error.message.slice(0, 240) : "Command failed"
      }))
      .finally(() => this.#inFlight.delete(key));
    this.#inFlight.set(key, task);
    return task;
  }

  private assertAllowed(command: OperatorCommand): void {
    if (!this.#capabilities.has(command.capability)) throw new Error(`Capability '${command.capability}' is not available`);
    if (command.risk === "publish") throw new Error("Publish commands require the external human gate");
  }
}
