import type { RuntimeEvent } from "../contracts";

export type InputIntent =
  | { source: "mouse" | "touch" | "keyboard" | "search" | "route" | "fallback"; verb: "inspect"; entityId?: string }
  | { source: "mouse" | "touch" | "keyboard" | "search" | "route" | "fallback"; verb: "select" | "read" | "recenter"; entityId: string };

export class InputController {
  normalize(intent: InputIntent): RuntimeEvent {
    switch (intent.verb) {
      case "inspect":
        return { type: "inspectHover", entityId: intent.entityId };
      case "select":
        return { type: "selectEntity", entityId: intent.entityId };
      case "read":
        return { type: "readEntity", entityId: intent.entityId };
      case "recenter":
        return { type: "selectCenter", entityId: intent.entityId };
    }
  }
}
