import { expect, it } from "vitest";
import cases from "./fixtures/action-dialogue-relationships.json";
import { isDialogueHistory } from "./actionBoard";

// The Python contract reads these same public synthetic histories.
it.each(cases)("validates stored dialogue relationships: $name", ({ events, valid }) => {
  expect(isDialogueHistory(events)).toBe(valid);
});
