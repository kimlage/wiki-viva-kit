// Command registry (god-mode plan §10.3): a declarative table instead of `if`
// chains spread through WorldView/CommandBar. The registry resolves alias
// phrases to typed invocations; it never executes anything and never talks to
// the network — execution authority stays server-side (plan §11).

import type { AdminCommandDefinition, CommandParameter } from "./types";

export const COMMAND_MESSAGE_KEYS = {
  empty: "command.invalid.empty",
  unknown: "command.invalid.unknown",
  missingArgument: "command.invalid.missingArgument",
  unexpectedArgument: "command.invalid.unexpectedArgument",
  badArgument: "command.invalid.badArgument"
} as const;

export type CommandResolution =
  | { ok: true; definition: AdminCommandDefinition; args: Record<string, string> }
  | { ok: false; messageKey: string };

export type CommandRegistry = {
  definitions: readonly AdminCommandDefinition[];
  byAlias: ReadonlyMap<string, AdminCommandDefinition>;
  byId: ReadonlyMap<string, AdminCommandDefinition>;
};

export function buildCommandRegistry(
  definitions: readonly AdminCommandDefinition[]
): CommandRegistry {
  const byAlias = new Map<string, AdminCommandDefinition>();
  const byId = new Map<string, AdminCommandDefinition>();
  for (const definition of definitions) {
    if (byId.has(definition.id)) {
      throw new Error(`duplicate command id: ${definition.id}`);
    }
    byId.set(definition.id, definition);
    for (const alias of definition.aliases) {
      const normalized = alias.trim().toLowerCase();
      if (normalized !== alias) {
        throw new Error(`alias must be lowercase and trimmed: "${alias}" (${definition.id})`);
      }
      if (byAlias.has(normalized)) {
        throw new Error(`duplicate command alias: "${alias}"`);
      }
      byAlias.set(normalized, definition);
    }
  }
  return { definitions, byAlias, byId };
}

// Resolve a tokenized invocation: the longest alias phrase matching the
// leading tokens wins; the remaining tokens bind positionally to the
// definition's parameters. Alias matching is case-insensitive; argument
// values keep their original casing unless constrained by a closed value set.
export function resolveCommandTokens(
  registry: CommandRegistry,
  tokens: readonly string[]
): CommandResolution {
  if (tokens.length === 0) return { ok: false, messageKey: COMMAND_MESSAGE_KEYS.empty };
  for (let take = tokens.length; take >= 1; take -= 1) {
    const phrase = tokens.slice(0, take).join(" ").toLowerCase();
    const definition = registry.byAlias.get(phrase);
    if (!definition) continue;
    return bindArguments(definition, tokens.slice(take));
  }
  return { ok: false, messageKey: COMMAND_MESSAGE_KEYS.unknown };
}

function bindArguments(
  definition: AdminCommandDefinition,
  rest: readonly string[]
): CommandResolution {
  if (rest.length > definition.parameters.length) {
    return { ok: false, messageKey: COMMAND_MESSAGE_KEYS.unexpectedArgument };
  }
  const args: Record<string, string> = {};
  for (let index = 0; index < definition.parameters.length; index += 1) {
    const parameter = definition.parameters[index];
    const token = rest[index];
    if (token === undefined) {
      if (parameter.required) {
        return { ok: false, messageKey: COMMAND_MESSAGE_KEYS.missingArgument };
      }
      continue;
    }
    const value = normalizeParameterValue(parameter, token);
    if (value === null) return { ok: false, messageKey: COMMAND_MESSAGE_KEYS.badArgument };
    args[parameter.name] = value;
  }
  return { ok: true, definition, args };
}

function normalizeParameterValue(parameter: CommandParameter, token: string): string | null {
  if (!parameter.values) return token;
  const lowered = token.toLowerCase();
  return parameter.values.includes(lowered) ? lowered : null;
}

// History redaction helper (§10.4): sensitive argument values never enter the
// in-memory history. Pure string surgery so the recalled entry still reads as
// what the operator typed.
export function redactSensitiveArgs(
  definition: AdminCommandDefinition,
  args: Record<string, string>,
  entry: string
): string {
  let redacted = entry;
  for (const parameter of definition.parameters) {
    const value = args[parameter.name];
    if (!parameter.sensitive || !value) continue;
    redacted = redacted.split(value).join("•••");
  }
  return redacted;
}
