import { getAdminSessionToken } from "../../application/adminSession";
import type { ContextBlocker, ContextPacket, ContextPacketCapability, ContextPacketRequest, ContextPacketResult } from "../../data/contextPackets";
import { operatorPost, operatorRequest } from "./operatorClient";

type Row = Record<string, unknown>;
const row = (value: unknown): value is Row => Boolean(value && typeof value === "object" && !Array.isArray(value));
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const optionalText = (value: unknown) => value === null || typeof value === "string";
const revision = (value: unknown): value is string => typeof value === "string" && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value);
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const count = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const unknown = (): ContextPacketResult => ({ ok: false, error_code: "context_packet_unknown", blocker: null });

export async function loadContextPacketCapability(options?: { signal?: AbortSignal }): Promise<ContextPacketCapability> {
  const token = getAdminSessionToken();
  const response = await operatorRequest("/coordination/protected-capability", { cache: "no-store", signal: options?.signal,
    headers: token ? { "X-Wiki-Admin-Session": token } : {} });
  if (!response.ok) throw new Error("context_capability_unknown");
  const value: unknown = await response.json();
  if (!row(value) || value.ok !== true || value.schema_version !== "wiki.coordination-capability/v1") throw new Error("context_capability_unknown");
  if (value.available === false && value.reason === "not_available_or_not_authorized") return value as ContextPacketCapability;
  if (value.available === true && strings(value.contexts) && value.contexts.length > 0 && revision(value.policy_revision)) return value as ContextPacketCapability;
  throw new Error("context_capability_unknown");
}
function blocker(value: unknown): value is ContextBlocker {
  return row(value) && ["action", "target", "reason", "owner", "required_action", "resume_condition"].every(k => text(value[k]) && String(value[k]).length <= 4000)
    && optionalText(value.interface) && ["pending", "denied", "uncertain"].includes(String(value.status));
}
function packet(value: unknown, request: ContextPacketRequest): value is ContextPacket {
  if (!row(value) || value.schema_version !== "wiki.task-context/v1" || value.task_id !== request.task.task_id || value.context_id !== request.context_id
    || value.content_revision !== request.content_revision || value.policy_revision !== request.approved_revision || !hash(value.packet_digest)
    || !text(value.enforcement_claim) || value.goal !== request.task.goal || value.output !== request.task.output || value.integrator !== request.task.integrator
    || value.max_bytes !== request.task.max_bytes || !count(value.bytes_used) || value.bytes_used > request.task.max_bytes
    || !count(value.selected_text_bytes) || value.selected_text_bytes > value.bytes_used) return false;
  const coverage = value.coverage, context = value.context;
  if (!row(coverage) || coverage.mode !== "explicit_read_set" || coverage.complete !== false || !strings(coverage.missing)
    || !row(context) || context.id !== request.context_id || !["purpose", "owner", "root", "boundary"].every(k => text(context[k])) || !strings(context.lineage)) return false;
  const inputs = value.inputs, bytesUsed = value.bytes_used;
  if (!Array.isArray(inputs) || !inputs.every(item => row(item) && ["mandatory", "evidence"].includes(String(item.kind))
    && ["ref", "reason"].every(k => text(item[k])) && optionalText(item.section) && optionalText(item.field) && typeof item.text === "string"
    && count(item.byte_length) && item.byte_length <= bytesUsed && new TextEncoder().encode(item.text).length === item.byte_length && hash(item.sha256) && hash(item.document_sha256) && revision(item.revision))) return false;
  if (!request.task.evidence.every(e => inputs.some((item: Row) => item.kind === "evidence" && item.ref === e.ref
    && (item.section ?? undefined) === e.section && (item.field ?? undefined) === e.field
    && (!e.expected_document_sha256 || item.document_sha256 === e.expected_document_sha256)))) return false;
  const declared = value.declared_read_set;
  return Array.isArray(declared) && declared.every(item => row(item) && text(item.ref)
    && optionalText(item.section) && optionalText(item.field) && revision(item.revision))
    && inputs.every(item => declared.some(selection => selection.ref === item.ref && selection.section === item.section && selection.field === item.field && selection.revision === item.revision))
    && Array.isArray(value.required_capabilities) && value.required_capabilities.every(item => row(item) && text(item.capability) && text(item.target));
}
export async function prepareContextPacket(request: ContextPacketRequest, options?: { signal?: AbortSignal }): Promise<ContextPacketResult> {
  try {
    const response = await operatorPost("/coordination/protected/packet", request, { signal: options?.signal });
    const value: unknown = await response.json();
    if (response.ok && row(value) && value.ok === true && value.mode === "approved" && packet(value.packet, request)) return value as ContextPacketResult;
    if (!response.ok && row(value) && value.ok === false && blocker(value.blocker)) return { ok: false, error_code: "context_packet_blocked", blocker: value.blocker };
    return unknown();
  } catch { return unknown(); }
}
