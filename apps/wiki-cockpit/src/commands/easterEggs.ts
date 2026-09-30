// Easter-egg invocations (god-mode plan §5). The ritual phrase is a fun
// discovery, never a credential: matching it starts a visual journey and a
// truthful explanation of the operator state — it grants nothing.

import type { EasterEggId } from "./types";

export type EasterEggDefinition = {
  id: EasterEggId;
  phrase: string;
};

export const TAKEZO_RITUAL_PHRASE = "abrachaindabra";

// v1 recognizes ONLY the single-word phrase. The spaced alias
// ("abra chain dabra") stays a future option by explicit decision (§5.2).
export const EASTER_EGGS: readonly EasterEggDefinition[] = [
  { id: "takezo_ritual", phrase: TAKEZO_RITUAL_PHRASE }
];

// Safe normalization (§5.2): trim at the edges + case-insensitive. Internal
// whitespace must match exactly. No fuzzy matching, no autocorrection, no
// suggestion in the regular autocomplete.
export function matchEasterEgg(rawInput: string): EasterEggDefinition | null {
  const normalized = rawInput.trim().toLowerCase();
  return EASTER_EGGS.find((egg) => egg.phrase === normalized) ?? null;
}
