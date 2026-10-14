import type { PageRecord } from "../types";
import { operatorPost } from "../world/clients/operatorClient";

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
  cancellation_receipt?: string; priority?: string;
};
export async function saveAction(edit: ActionEdit): Promise<void> {
  const response = await operatorPost("/actions/transition", edit);
  if (!response.ok) {
    const result = await response.json();
    throw new Error(String(result.error_code || result.error || `HTTP ${response.status}`));
  }
}
