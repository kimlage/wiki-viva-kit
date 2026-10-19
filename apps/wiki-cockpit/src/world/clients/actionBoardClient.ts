import { operatorPost, operatorRequest } from "./operatorClient";
import type { ActionEdit, ActionSaveResult } from "../../data/actionBoard";

export async function saveAction(edit: ActionEdit): Promise<ActionSaveResult> {
  const response = await operatorPost("/actions/transition", edit);
  if (!response.ok) {
    const result = await response.json();
    throw new Error(String(result.error_code || result.error || `HTTP ${response.status}`));
  }
  try { return await response.json() as ActionSaveResult; }
  catch { return { answer_observation: { status: "unknown" } }; }
}

export async function loadCoordination(): Promise<import("../../data/actionBoard").CoordinationIndex> {
  const response = await operatorRequest("/coordination", { cache: "no-store" });
  if (!response.ok) throw new Error("Coordinator mapping unavailable");
  return response.json();
}
