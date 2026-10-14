import type { PageRecord } from "../types";

export const ACTION_STATES = ["open", "in_progress", "waiting_human", "blocked", "done", "cancelled"] as const;
export type ActionState = typeof ACTION_STATES[number];
export const ACTION_TRANSITIONS: Record<ActionState, readonly ActionState[]> = {
  open: ["in_progress", "blocked", "waiting_human", "done", "cancelled"],
  in_progress: ["blocked", "waiting_human", "done", "cancelled"],
  blocked: ["open", "in_progress", "waiting_human", "cancelled"],
  waiting_human: ["in_progress", "blocked", "done", "cancelled"], done: [], cancelled: []
};
export function actionState(page: PageRecord): ActionState | "unknown" {
  const state = String(page.work?.state || "");
  return ACTION_STATES.includes(state as ActionState) ? state as ActionState : "unknown";
}
export function boardPages(pages: PageRecord[], context: string, query: string, terminal: boolean): PageRecord[] {
  const rank: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 };
  return pages.filter(p => p.page_type === "action")
    .filter(p => !context || p.context === context)
    .filter(p => terminal || !["done", "cancelled"].includes(actionState(p)))
    .filter(p => [p.title, p.id, p.work?.owner_ref, p.work?.next_action, p.work?.blocker_reason].join(" ").toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    .sort((a, b) => (rank[String(a.work?.priority)] ?? 2) - (rank[String(b.work?.priority)] ?? 2) || a.title.localeCompare(b.title));
}
export type ActionEdit = {
  page_ref: string; expected_sha256: string; next_state: ActionState;
  next_action?: string; blocker_reason?: string; completion_receipt?: string;
  cancellation_receipt?: string; priority?: string; dialogue_event?: DialogueInput;
};

export type CoordinationIndex = {
  schema_version: string; configured: boolean; snapshot_id: string;
  profiles: { id: string; label: string; scope: string; action_ids: string[]; access_requirements?: {service: string; expected_identity: string; method: string; source_ref: string}[] }[];
  actions: { action_id: string; coordinator: string | null; content_sha256: string; dialogue?: {pending_question_ids: string[]} }[];
};

export type DialogueInput = {
  event_id: string; kind: "direction" | "question" | "confirmation_request" | "answer" | "comment";
  text: string; coordinator: string; reply_to?: string;
};
export type DialogueEvent = DialogueInput & { actor: string; at: string; before_sha256: string };

// Page frontmatter also comes from static snapshots; TypeScript casts cannot
// validate it. Keep malformed records out of render and reply controls.
export function isDialogueHistory(value: unknown): value is DialogueEvent[] {
  if (!Array.isArray(value) || value.length > 500) return false;
  const ids = new Set<string>();
  return value.every(event => {
    if (!event || typeof event !== "object" || Array.isArray(event)) return false;
    for (const key of ["event_id", "kind", "text", "coordinator", "actor", "at", "before_sha256"]) {
      if (typeof event[key] !== "string") return false;
    }
    if (!/^[a-zA-Z0-9_-]{8,80}$/.test(event.event_id) || ids.has(event.event_id)
      || !["direction", "question", "confirmation_request", "answer", "comment"].includes(event.kind)
      || !event.text.trim() || event.text.length > 2000
      || !/^[a-z][a-z0-9_-]{0,63}$/.test(event.coordinator)
      || !["operator", `coordinator:${event.coordinator}`].includes(event.actor)
      || !/^[0-9a-f]{64}$/.test(event.before_sha256)
      || (event.reply_to !== undefined && typeof event.reply_to !== "string")) return false;
    ids.add(event.event_id);
    return true;
  });
}
