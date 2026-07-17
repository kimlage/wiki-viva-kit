// Input interpretation for the CommandBar Enter handler (god-mode plan §10.1):
// (1) normalize, (2) test exact invocations (`abrachaindabra`, `god_mode` and
// its registered subcommands), (3) route the explicit "> " / "/admin" prefixes
// through the command registry, (4) otherwise leave the search flow untouched.
// This runs ONLY on the focused CommandBar input — never as a global listener.

import { ADMIN_COMMAND_REGISTRY, GOD_MODE_COMMAND_ID } from "./adminCommands";
import { matchEasterEgg } from "./easterEggs";
import { COMMAND_MESSAGE_KEYS, redactSensitiveArgs, resolveCommandTokens } from "./registry";
import type { ParsedInput } from "./types";

export const EXPLICIT_COMMAND_PREFIX = ">";
export const EXPLICIT_ADMIN_PREFIX = "/admin";

// Explicit command mode drives command-only affordances (↑/↓ history, Escape
// back to search). Exact bare invocations are NOT command mode: while typing
// them the field still behaves as plain search (§10.4).
export function isExplicitCommandDraft(value: string): boolean {
  const lead = value.trimStart().toLowerCase();
  if (lead.startsWith(EXPLICIT_COMMAND_PREFIX)) return true;
  return lead === EXPLICIT_ADMIN_PREFIX || lead.startsWith(`${EXPLICIT_ADMIN_PREFIX} `);
}

export type ParseCommandOptions = {
  // Presentation flag (plan §17.2/§28): when the runtime config disables the
  // easter egg, the ritual phrase behaves as plain search — no reveal, no
  // rebuild required to turn it off.
  easterEggEnabled?: boolean;
};

export function parseCommandInput(raw: string, options: ParseCommandOptions = {}): ParsedInput {
  const egg = options.easterEggEnabled === false ? null : matchEasterEgg(raw);
  if (egg) return { kind: "easter_egg", id: egg.id };

  const trimmed = raw.trim();
  if (trimmed.startsWith(EXPLICIT_COMMAND_PREFIX)) {
    return parseExplicit(trimmed.slice(EXPLICIT_COMMAND_PREFIX.length));
  }
  const lowered = trimmed.toLowerCase();
  if (lowered === EXPLICIT_ADMIN_PREFIX || lowered.startsWith(`${EXPLICIT_ADMIN_PREFIX} `)) {
    return parseExplicit(`admin ${trimmed.slice(EXPLICIT_ADMIN_PREFIX.length)}`);
  }

  // Bare exact invocations: only `god_mode [status|off]`. Anything that does
  // not resolve exactly ("god_mode gato") stays normal search — the bare
  // vocabulary never captures search traffic on a near miss.
  const tokens = tokenize(trimmed);
  if (tokens[0]?.toLowerCase() === GOD_MODE_COMMAND_ID) {
    const resolved = resolveCommandTokens(ADMIN_COMMAND_REGISTRY, tokens);
    if (resolved.ok) {
      return { kind: "admin_command", commandId: resolved.definition.id, args: resolved.args };
    }
  }

  return { kind: "search", query: raw };
}

// Explicit mode is loud: an unresolved invocation is an error message with a
// help hint, never a silent fallback to search.
function parseExplicit(rest: string): ParsedInput {
  const tokens = tokenize(rest);
  if (tokens.length === 0) return { kind: "invalid_command", messageKey: COMMAND_MESSAGE_KEYS.empty };
  const resolved = resolveCommandTokens(ADMIN_COMMAND_REGISTRY, tokens);
  if (!resolved.ok) return { kind: "invalid_command", messageKey: resolved.messageKey };
  return { kind: "admin_command", commandId: resolved.definition.id, args: resolved.args };
}

function tokenize(value: string): string[] {
  return value.split(/\s+/).filter(Boolean);
}

// What (if anything) the in-memory session history may record for a submitted
// input (§10.4): search input and the ritual phrase are never recorded;
// sensitive parameter values are redacted. Unlock codes are typed into the
// dedicated unlock dialog (PR3), never into this field — if that ever changes,
// this function is the choke point that must redact them.
export function commandHistoryEntry(raw: string): string | null {
  const parsed = parseCommandInput(raw);
  if (parsed.kind === "search" || parsed.kind === "easter_egg") return null;
  const entry = raw.trim();
  if (parsed.kind === "invalid_command") return entry;
  const definition = ADMIN_COMMAND_REGISTRY.byId.get(parsed.commandId);
  if (!definition) return entry;
  return redactSensitiveArgs(definition, parsed.args, entry);
}
