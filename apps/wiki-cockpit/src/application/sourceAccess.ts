import type { SourceEntity, SourceConnectionBinding, SourceExecutionBinding } from "../types";

export type HostAction = "routes" | "inspect" | "transport_metadata" | "configure" | "read_test" | "read_receipts" | "open_native";
export type GatewayOriginMetadata = { schema_version: "hermes.connector_gateway_origin.v1"; status: "known" | "unknown"; profile: string | null;
  origin: { scheme: "http" | "https"; host: string; port: number } | null; provenance: "default" | "override" | "derived" | "unknown";
  resolution_scope: "process"; reason_code: string | null; account_identity_verified: false; account_enforced: false };
export type ExecutorRoute = { connectionId: string; profile: string; targetProfile: string; mode: "local" | "remote"; key: string; label?: string };
export type NativeSourceBinding = { source_id: string; context: string; source_kind: string; binding_sha256: string; config_sha256: string; access_policy: SourceEntity["access_policy"]; locator?: string; auth?: SourceEntity["auth"]; execution_hold?: string };
export type NativeReadReceipt = { schema_version: string; source_id: string; binding_sha256: string; config_sha256: string; status: string;
  request_id?: string; tool_refs?: {id:string;name:string;outcome?:string}[];
  native_submission_status?: "queued" | "submitted";
  checked_at?: string; valid_until?: string; execution?: SourceExecutionBinding | (SourceConnectionBinding & {method: "profile_bot"}); owner_stored_session_id?: string; error_code?: string;
  executor_pid?: number; identity?: { status: string; confirmed_identity?: string }; commit_before?: string; commit_after?: string; observed_permissions?: string[] };
export type HostResult = { unresolved_request?: string; execution_hold?: string; routes?: ExecutorRoute[]; binding?: NativeSourceBinding; route?: ExecutorRoute; gateway_origin?: GatewayOriginMetadata;
  providers?: { id: string; label: string; method: "native_session" }[];
  sessions?: {id:string;title:string}[]; toolsets?: {name:string;enabled:boolean;tools:string[]}[];
  accounts?: { id: string; connector: string; alias: string; label: string; status: string }[]; accounts_available?: boolean;
  managed_available?: boolean; mcp_available?: boolean; support_errors?: (string|null)[]; receipts?: NativeReadReceipt[] } & Partial<NativeReadReceipt>;

export interface SourceHostPort {
  connect(): Promise<void>;
  subscribeActivity?(listener: () => void): () => void;
  request(source: SourceEntity, action: HostAction, routeKey?: string, configSha?: string, setupMethod?: string): Promise<HostResult>;
  close(): void;
}
