import { afterEach, describe, expect, it } from "vitest";
import { configureLanguage, t } from "../data/i18n";
import { ADMIN_COMMANDS } from "./adminCommands";
import { COMMAND_MESSAGE_KEYS } from "./registry";
import { commandHistoryEntry, isExplicitCommandDraft, parseCommandInput } from "./parser";

afterEach(() => configureLanguage("en"));

describe("parseCommandInput — easter egg (plan §5.2, §22.1)", () => {
  it("recognizes the exact ritual phrase", () => {
    expect(parseCommandInput("abrachaindabra")).toEqual({ kind: "easter_egg", id: "takezo_ritual" });
  });

  it("trims edges and ignores case", () => {
    expect(parseCommandInput(" ABRACHAINDABRA ")).toEqual({ kind: "easter_egg", id: "takezo_ritual" });
    expect(parseCommandInput("AbraChainDabra")).toEqual({ kind: "easter_egg", id: "takezo_ritual" });
  });

  it("never matches fuzzily — a near miss stays search", () => {
    expect(parseCommandInput("abrachaindabr")).toEqual({ kind: "search", query: "abrachaindabr" });
    expect(parseCommandInput("abrachaindabraa")).toEqual({ kind: "search", query: "abrachaindabraa" });
  });

  it("keeps extra words as plain search", () => {
    expect(parseCommandInput("abrachaindabra gato")).toEqual({ kind: "search", query: "abrachaindabra gato" });
  });

  it("does not enable the spaced alias in v1", () => {
    expect(parseCommandInput("abra chain dabra")).toEqual({ kind: "search", query: "abra chain dabra" });
  });

  it("stays plain search when the takezo_easter_egg presentation flag is off", () => {
    expect(parseCommandInput("abrachaindabra", { easterEggEnabled: false })).toEqual({
      kind: "search",
      query: "abrachaindabra"
    });
    expect(parseCommandInput("abrachaindabra", { easterEggEnabled: true })).toEqual({
      kind: "easter_egg",
      id: "takezo_ritual"
    });
  });
});

describe("parseCommandInput — bare god_mode invocations (plan §10.5)", () => {
  it("recognizes god_mode without arguments", () => {
    expect(parseCommandInput("god_mode")).toEqual({ kind: "admin_command", commandId: "god_mode", args: {} });
  });

  it("recognizes the status and off subcommands, case-insensitively", () => {
    expect(parseCommandInput("GOD_MODE STATUS")).toEqual({
      kind: "admin_command",
      commandId: "god_mode",
      args: { subcommand: "status" }
    });
    expect(parseCommandInput("god_mode off")).toEqual({
      kind: "admin_command",
      commandId: "god_mode",
      args: { subcommand: "off" }
    });
  });

  it("leaves unknown bare subcommands as normal search", () => {
    expect(parseCommandInput("god_mode gato")).toEqual({ kind: "search", query: "god_mode gato" });
    expect(parseCommandInput("god_mode status extra")).toEqual({
      kind: "search",
      query: "god_mode status extra"
    });
  });
});

describe("parseCommandInput — explicit prefixes (plan §10.1)", () => {
  it("routes \"> \" and \"/admin\" through the registry", () => {
    expect(parseCommandInput("> admin overview")).toEqual({
      kind: "admin_command",
      commandId: "admin.overview",
      args: {}
    });
    expect(parseCommandInput("/admin overview")).toEqual({
      kind: "admin_command",
      commandId: "admin.overview",
      args: {}
    });
    expect(parseCommandInput(">admin git status")).toEqual({
      kind: "admin_command",
      commandId: "admin.git_status",
      args: {}
    });
  });

  it("binds positional arguments and preserves their casing", () => {
    expect(parseCommandInput("> admin source plan Fin-01")).toEqual({
      kind: "admin_command",
      commandId: "admin.source_plan",
      args: { id: "Fin-01" }
    });
    expect(parseCommandInput("/admin vision preview impact-radius")).toEqual({
      kind: "admin_command",
      commandId: "admin.vision_preview",
      args: { id: "impact-radius" }
    });
  });

  it("is loud about invalid explicit input instead of falling back to search", () => {
    expect(parseCommandInput(">")).toEqual({ kind: "invalid_command", messageKey: COMMAND_MESSAGE_KEYS.empty });
    expect(parseCommandInput("/admin")).toEqual({
      kind: "invalid_command",
      messageKey: COMMAND_MESSAGE_KEYS.unknown
    });
    expect(parseCommandInput("> admin nope")).toEqual({
      kind: "invalid_command",
      messageKey: COMMAND_MESSAGE_KEYS.unknown
    });
    expect(parseCommandInput("> admin source plan")).toEqual({
      kind: "invalid_command",
      messageKey: COMMAND_MESSAGE_KEYS.missingArgument
    });
    expect(parseCommandInput("> admin overview extra")).toEqual({
      kind: "invalid_command",
      messageKey: COMMAND_MESSAGE_KEYS.unexpectedArgument
    });
    expect(parseCommandInput("> god_mode wat")).toEqual({
      kind: "invalid_command",
      messageKey: COMMAND_MESSAGE_KEYS.badArgument
    });
  });
});

describe("parseCommandInput — search stays untouched", () => {
  it("returns the raw input for ordinary queries", () => {
    expect(parseCommandInput("finance overview")).toEqual({ kind: "search", query: "finance overview" });
    expect(parseCommandInput("  spaced query ")).toEqual({ kind: "search", query: "  spaced query " });
    expect(parseCommandInput("")).toEqual({ kind: "search", query: "" });
  });
});

describe("isExplicitCommandDraft (plan §10.4)", () => {
  it("marks only the explicit prefixes as command mode", () => {
    expect(isExplicitCommandDraft("> admin overview")).toBe(true);
    expect(isExplicitCommandDraft(">")).toBe(true);
    expect(isExplicitCommandDraft("/admin")).toBe(true);
    expect(isExplicitCommandDraft("/ADMIN overview")).toBe(true);
    expect(isExplicitCommandDraft("god_mode")).toBe(false);
    expect(isExplicitCommandDraft("abrachaindabra")).toBe(false);
    expect(isExplicitCommandDraft("/administer")).toBe(false);
    expect(isExplicitCommandDraft("plain search")).toBe(false);
  });
});

describe("commandHistoryEntry (plan §10.4)", () => {
  it("never records search input or the ritual phrase", () => {
    expect(commandHistoryEntry("plain search")).toBeNull();
    expect(commandHistoryEntry(" ABRACHAINDABRA ")).toBeNull();
  });

  it("records commands trimmed, including recallable invalid attempts", () => {
    expect(commandHistoryEntry(" > admin overview ")).toBe("> admin overview");
    expect(commandHistoryEntry("god_mode status")).toBe("god_mode status");
    expect(commandHistoryEntry("> admin nope")).toBe("> admin nope");
  });
});

describe("command copy (i18n EN/PT)", () => {
  const messageKeys = [
    ...Object.values(COMMAND_MESSAGE_KEYS),
    ...ADMIN_COMMANDS.map((definition) => definition.helpKey),
    "command.godMode.locked",
    "command.godMode.alreadyLocked",
    "command.admin.locked"
  ];

  it("resolves every parser-facing key in both languages", () => {
    for (const lang of ["en", "pt"] as const) {
      configureLanguage(lang);
      for (const key of messageKeys) {
        expect(t(key), `${lang}:${key}`).not.toBe(key);
      }
    }
  });
});
