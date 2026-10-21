import type { SourceEntity } from "../types";

export type HostAction = "routes" | "inspect" | "configure" | "read_test" | "read_receipts";
export type ExecutorRoute = { connectionId: string; profile: string; targetProfile: string; mode: "local" | "remote"; key: string };
export type NativeSourceBinding = { source_id: string; context: string; source_kind: string; binding_sha256: string; config_sha256: string; access_policy: SourceEntity["access_policy"]; resource_options?: { id: string; target: string; source_scope: string; permission: string }[] };
export type NativeReadReceipt = { schema_version: string; source_id: string; binding_sha256: string; config_sha256: string; status: string;
  request_id?: string;
  checked_at?: string; valid_until?: string; execution?: NonNullable<SourceEntity["access_policy"]>["execution"]; error_code?: string;
  executor_pid?: number; identity?: { status: string; confirmed_identity?: string }; commit_before?: string; commit_after?: string; observed_permissions?: string[] };
export type HostResult = { unresolved_request?: string; routes?: ExecutorRoute[]; binding?: NativeSourceBinding; route?: ExecutorRoute;
  providers?: { id: string; label: string; method: "managed_connector" | "mcp" }[];
  accounts?: { id: string; connector: string; alias: string; label: string; status: string }[];
  managed_available?: boolean; mcp_available?: boolean; support_errors?: (string|null)[]; receipts?: NativeReadReceipt[] } & Partial<NativeReadReceipt>;

export interface SourceHostPort {
  connect(): Promise<void>;
  request(source: SourceEntity, action: HostAction, routeKey?: string, configSha?: string, setupMethod?: string): Promise<HostResult>;
  close(): void;
}
