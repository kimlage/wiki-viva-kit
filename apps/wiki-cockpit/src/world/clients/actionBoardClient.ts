import { operatorPost, operatorRequest } from "./operatorClient";
import type { ActionEdit, ActionSaveResult, ActionCreate, ActionCreated, ActionCreationOptions } from "../../data/actionBoard";

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


export async function loadActionCreationOptions(): Promise<ActionCreationOptions> {
  const response = await operatorRequest("/actions/create", { cache: "no-store" });
  if (!response.ok) throw new Error("Action creation unavailable");
  return response.json();
}

export async function createAction(input: ActionCreate): Promise<ActionCreated> {
  const response = await operatorPost("/actions/create", input);
  if (!response.ok) {
    const result = await response.json();
    throw new Error(String(result.error_code || result.error || `HTTP ${response.status}`));
  }
  // Never invent a successful page or retry under another title after a lost response.
  const result = await response.json() as ActionCreated;
  if (!result.created || !result.page_id || !result.after_sha256) throw new Error("creation_result_unknown");
  return result;
}
