import { operatorPost } from "./operatorClient";
import type { ActionEdit } from "../../data/actionBoard";

export async function saveAction(edit: ActionEdit): Promise<void> {
  const response = await operatorPost("/actions/transition", edit);
  if (!response.ok) {
    const result = await response.json();
    throw new Error(String(result.error_code || result.error || `HTTP ${response.status}`));
  }
}
