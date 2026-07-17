import { describe, expect, it } from "vitest";
import { ADMIN_COMMAND_REGISTRY, ADMIN_COMMANDS } from "./adminCommands";
import {
  buildCommandRegistry,
  COMMAND_MESSAGE_KEYS,
  redactSensitiveArgs,
  resolveCommandTokens
} from "./registry";
import type { AdminCommandDefinition } from "./types";

const readCommand = (overrides: Partial<AdminCommandDefinition>): AdminCommandDefinition => ({
  id: "test.command",
  aliases: ["test command"],
  capability: ["system.inspect"],
  risk: "read",
  parameters: [],
  helpKey: "command.help.admin_overview",
  ...overrides
});

describe("buildCommandRegistry", () => {
  it("rejects duplicate ids and aliases at construction time", () => {
    expect(() =>
      buildCommandRegistry([readCommand({}), readCommand({ aliases: ["other alias"] })])
    ).toThrow(/duplicate command id/);
    expect(() =>
      buildCommandRegistry([
        readCommand({}),
        readCommand({ id: "test.other", aliases: ["test command"] })
      ])
    ).toThrow(/duplicate command alias/);
  });

  it("rejects aliases that are not lowercase trimmed phrases", () => {
    expect(() => buildCommandRegistry([readCommand({ aliases: ["Test Command"] })])).toThrow(
      /alias must be lowercase/
    );
  });
});

describe("resolveCommandTokens", () => {
  const registry = buildCommandRegistry([
    readCommand({ id: "a.short", aliases: ["admin vision"] }),
    readCommand({
      id: "a.long",
      aliases: ["admin vision preview"],
      parameters: [{ name: "id", required: true }]
    }),
    readCommand({
      id: "a.enum",
      aliases: ["gate"],
      parameters: [{ name: "mode", required: false, values: ["on", "off"] }]
    })
  ]);

  it("prefers the longest alias match", () => {
    const resolved = resolveCommandTokens(registry, ["admin", "vision", "preview", "x1"]);
    expect(resolved.ok && resolved.definition.id).toBe("a.long");
    expect(resolved.ok && resolved.args).toEqual({ id: "x1" });
  });

  it("matches aliases case-insensitively", () => {
    const resolved = resolveCommandTokens(registry, ["Admin", "VISION"]);
    expect(resolved.ok && resolved.definition.id).toBe("a.short");
  });

  it("normalizes closed-set values and rejects everything else", () => {
    const ok = resolveCommandTokens(registry, ["gate", "OFF"]);
    expect(ok.ok && ok.args).toEqual({ mode: "off" });
    const bad = resolveCommandTokens(registry, ["gate", "sideways"]);
    expect(bad).toEqual({ ok: false, messageKey: COMMAND_MESSAGE_KEYS.badArgument });
  });

  it("reports empty, unknown, missing and unexpected input with typed keys", () => {
    expect(resolveCommandTokens(registry, [])).toEqual({
      ok: false,
      messageKey: COMMAND_MESSAGE_KEYS.empty
    });
    expect(resolveCommandTokens(registry, ["nope"])).toEqual({
      ok: false,
      messageKey: COMMAND_MESSAGE_KEYS.unknown
    });
    expect(resolveCommandTokens(registry, ["admin", "vision", "preview"])).toEqual({
      ok: false,
      messageKey: COMMAND_MESSAGE_KEYS.missingArgument
    });
    expect(resolveCommandTokens(registry, ["admin", "vision", "x", "y"])).toEqual({
      ok: false,
      messageKey: COMMAND_MESSAGE_KEYS.unexpectedArgument
    });
  });
});

describe("redactSensitiveArgs (plan §10.4)", () => {
  it("removes sensitive parameter values from a history entry", () => {
    const definition = readCommand({
      aliases: ["unlock"],
      parameters: [{ name: "code", required: true, sensitive: true }]
    });
    expect(redactSensitiveArgs(definition, { code: "s3cret" }, "> unlock s3cret")).toBe(
      "> unlock •••"
    );
  });

  it("leaves non-sensitive values intact", () => {
    const definition = readCommand({ parameters: [{ name: "id", required: true }] });
    expect(redactSensitiveArgs(definition, { id: "fin-01" }, "> test command fin-01")).toBe(
      "> test command fin-01"
    );
  });
});

describe("ADMIN_COMMANDS table (plan §10.5)", () => {
  it("covers every initial command id", () => {
    const ids = ADMIN_COMMANDS.map((definition) => definition.id);
    expect(ids).toEqual([
      "god_mode",
      "admin.overview",
      "admin.inspect_system",
      "admin.inspect_config",
      "admin.config_validate",
      "admin.config_diff",
      "admin.gates_run",
      "admin.sources_inspect",
      "admin.source_plan",
      "admin.git_status",
      "admin.git_proposals",
      "admin.work_jobs",
      "admin.vision_discover",
      "admin.vision_preview",
      "admin.vision_propose",
      "admin.audit_recent",
      "admin.recovery_options"
    ]);
  });

  it("declares at least one capability per command and no raw-shell risk levels", () => {
    for (const definition of ADMIN_COMMANDS) {
      expect(definition.capability.length, definition.id).toBeGreaterThan(0);
      expect(["read", "derive", "proposal_write", "external_write", "destructive"]).toContain(
        definition.risk
      );
    }
  });

  it("builds one valid shared registry", () => {
    expect(ADMIN_COMMAND_REGISTRY.byId.size).toBe(ADMIN_COMMANDS.length);
    expect(ADMIN_COMMAND_REGISTRY.byAlias.get("admin status")?.id).toBe("admin.overview");
  });
});
