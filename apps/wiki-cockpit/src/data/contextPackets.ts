export type ContextPacketCapability =
  | { ok: true; schema_version: "wiki.coordination-capability/v1"; available: false; reason: "not_available_or_not_authorized" }
  | { ok: true; schema_version: "wiki.coordination-capability/v1"; available: true; contexts: string[]; policy_revision: string };
export type ContextBlocker = {
  action: string; target: string; reason: string; owner: string; required_action: string;
  interface: string | null; resume_condition: string; status: "pending" | "denied" | "uncertain";
};
export type ContextPacketRequest = {
  context_id: string; approved_revision: string; content_revision: string;
  task: { task_id: string; goal: string; output: string; integrator: string; max_bytes: number;
    evidence: { ref: string; producer?: string; reason: string; use: string; classification: string;
      expected_document_sha256?: string; section?: string; field?: string }[]; omissions?: string[] };
};
export type ContextPacket = {
  schema_version: "wiki.task-context/v1"; context_id: string; task_id: string; goal: string; output: string; integrator: string;
  content_revision: string; policy_revision: string; packet_digest: string; bytes_used: number; max_bytes: number; selected_text_bytes: number;
  coverage: { mode: "explicit_read_set"; complete: false; missing: string[] };
  context: { id: string; purpose: string; owner: string; root: string; lineage: string[]; boundary: string };
  enforcement_claim: string;
  inputs: { kind: "mandatory" | "evidence"; ref: string; section: string | null; field: string | null;
    text: string; byte_length: number; sha256: string; document_sha256: string; revision: string; reason: string }[];
  declared_read_set: { ref: string; section: string | null; field: string | null; revision: string }[];
  required_capabilities: { capability: string; target: string }[];
};
export type ContextPacketResult = { ok: true; mode: "approved"; packet: ContextPacket }
  | { ok: false; error_code: string; blocker: ContextBlocker | null };
export type ContextPacketPort = {
  loadCapability: (options?: { signal?: AbortSignal }) => Promise<ContextPacketCapability>;
  preparePacket: (input: ContextPacketRequest, options?: { signal?: AbortSignal }) => Promise<ContextPacketResult>;
};
