import type { SourceEntity } from "../types";

import type { HostAction, HostResult, SourceHostPort } from "../application/sourceAccess";

const PROTOCOL = "wiki.source_access.v1";
const ACTIONS = new Set<HostAction>(["routes", "inspect", "configure", "read_test", "read_receipts", "open_native"]);

export class SourceHostBridge implements SourceHostPort {
  private channel = "";
  private origin = "";
  private allowed: string[] = [];
  private pending = new Map<string, { resolve: (value: HostResult) => void; reject: (error: Error) => void; timer: number; action: HostAction; recoveryKey?: string }>();
  private closed = false;
  private activityListeners=new Set<()=>void>();
  private observed=new Set<string>();
  subscribeActivity(listener:()=>void) {this.activityListeners.add(listener);return()=>{this.activityListeners.delete(listener);};}
  private port?: MessagePort;
  private readyResolve?: () => void;
  private readyReject?: (error: Error) => void;
  private readyTimer?: number;
  private recoveryKey(source: SourceEntity, routeKey?: string, configSha?: string) {
    if (!routeKey || !/^[a-f0-9]{64}$/.test(configSha || "")) throw new Error("source_binding_invalid");
    return "wiki.source-read-pending.v1:" + JSON.stringify([source.source_id, source.access?.binding_sha256, routeKey, configSha]);
  }
  private async json(path: string): Promise<unknown> {
    const response = await fetch(path, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(8000) });
    if (!response.ok || this.closed) throw new Error("source_host_not_allowed");
    return response.json();
  }
  private receive = (event: MessageEvent, pairedPort = false) => {
    if (this.closed || (!pairedPort && (event.source !== window.parent || !this.allowed.includes(event.origin)))) return;
    const m = event.data;
    if (!m || m.protocol !== PROTOCOL) return;
    if (m.kind === "hello" && typeof m.channel === "string" && /^[a-zA-Z0-9-]{16,80}$/.test(m.channel)) {
      if (this.channel && this.channel !== m.channel) return;
      this.channel = m.channel; this.origin = event.origin;
      window.clearTimeout(this.readyTimer); this.readyResolve?.(); return;
    }
    if(m.kind === "native_activity" && m.channel===this.channel && this.observed.has(JSON.stringify([m.source?.source_id,m.source?.binding_sha256,m.route_key,m.source?.config_sha256]))) {for(const listener of this.activityListeners)listener();return;}
    if (m.kind !== "response" || m.channel !== this.channel || (!pairedPort && event.origin !== this.origin)) return;
    const item = this.pending.get(m.request_id);
    if (!item) return;
    this.pending.delete(m.request_id); window.clearTimeout(item.timer);
    if (m.ok === true && m.result && typeof m.result === "object") {
      const result = m.result as HostResult;
      if (item.recoveryKey) {
        try {
          const unresolved = window.sessionStorage.getItem(item.recoveryKey);
          const receipt = item.action === "read_test" ? result : result.receipts?.find(row => row.request_id === unresolved);
          if (unresolved && receipt?.request_id === unresolved && ["native_trace_observed", "native_trace_failed", "not_submitted"].includes(receipt.status || "")) window.sessionStorage.removeItem(item.recoveryKey);
          else if (unresolved && item.action === "read_receipts" && !receipt) result.unresolved_request = unresolved;
        } catch { item.reject(new Error("source_read_recovery_unavailable")); return; }
      }
      item.resolve(result);
    } else {
      if (item.recoveryKey && item.action === "read_test" && ["source_binding_changed", "source_configuration_changed", "executor_profile_mismatch", "source_read_adapter_not_implemented"].includes(m.error_code)) window.sessionStorage.removeItem(item.recoveryKey);
      item.reject(new Error(typeof m.error_code === "string" && /^[a-z_]{1,80}$/.test(m.error_code) ? m.error_code : "executor_unavailable"));
    }
  };
  async connect() {
    if (window.parent === window) throw new Error("source_host_standalone");
    const configuration = await this.json("/wiki-cockpit.config.json") as { source_host_origins?: unknown; source_host_transport?: string };
    if (configuration.source_host_transport === "electron_message_port") {
      if (typeof MessageChannel === "undefined" || this.closed) throw new Error("source_host_not_allowed");
      const { challenge } = await this.json("/api/source-host/challenge") as { challenge?: string };
      if (this.closed || !challenge || !/^[a-f0-9]{48}$/.test(challenge)) throw new Error("source_host_not_allowed");
      const pair = new MessageChannel(); this.port = pair.port1;
      const ready = new Promise<void>((resolve, reject) => {
        this.readyResolve = resolve; this.readyReject = reject;
        this.readyTimer = window.setTimeout(() => reject(new Error("source_host_not_allowed")), 20000);
      });
      let attested = false;
      pair.port1.onmessage = event => {
        void (async () => {
          if (this.closed) return;
          if (!attested) {
            const value = await this.json("/api/source-host/status?challenge=" + challenge) as { attested?: boolean };
            if (value.attested !== true || this.closed) return;
            attested = true;
          }
          this.receive(event, true);
        })().catch(() => this.readyReject?.(new Error("source_host_not_allowed")));
      };
      pair.port1.start();
      // Opaque origins cannot be a literal targetOrigin. Only the non-secret
      // pairing challenge + dedicated port go to this exact parent window.
      // No source request is sent until our own server confirms native pairing.
      window.parent.postMessage({ protocol: PROTOCOL, kind: "ready", challenge }, "*", [pair.port2]);
      return ready;
    }
    this.allowed = Array.isArray(configuration.source_host_origins) ? configuration.source_host_origins.filter((v): v is string => {
      if (typeof v !== "string") return false;
      try { const u = new URL(v); return ["http:", "https:"].includes(u.protocol) && u.origin === v && !u.username && !u.password; } catch { return false; }
    }) : [];
    if (!this.allowed.length || this.closed) throw new Error("source_host_not_allowed");
    window.addEventListener("message", this.receive);
    const ready = new Promise<void>((resolve, reject) => {
      this.readyResolve = resolve; this.readyReject = reject;
      this.readyTimer = window.setTimeout(() => reject(new Error("executor_unavailable")), 8000);
    });
    for (const origin of this.allowed) window.parent.postMessage({ protocol: PROTOCOL, kind: "ready" }, origin);
    return ready;
  }
  request(source: SourceEntity, action: HostAction, routeKey?: string, configSha?: string, setupMethod?: string): Promise<HostResult> {
    if (this.closed || !this.channel || !ACTIONS.has(action) || !/^[a-f0-9]{64}$/.test(source.access?.binding_sha256 || "")) return Promise.reject(new Error("source_binding_invalid"));
    if(routeKey && configSha)this.observed.add(JSON.stringify([source.source_id,source.access?.binding_sha256,routeKey,configSha]));
    const requestId = "wiki-" + crypto.randomUUID();
    let recoveryKey: string | undefined;
    if (action === "read_test" || action === "read_receipts") {
      try {
        recoveryKey = this.recoveryKey(source, routeKey, configSha);
        if (action === "read_test") {
          if (window.sessionStorage.getItem(recoveryKey)) return Promise.reject(new Error("source_read_result_unknown"));
          window.sessionStorage.setItem(recoveryKey, requestId);
        }
      } catch { return Promise.reject(new Error("source_read_recovery_unavailable")); }
    }
    const promise = new Promise<HostResult>((resolve, reject) => {
      const timer = window.setTimeout(() => { this.pending.delete(requestId); reject(new Error(action === "read_test" ? "source_read_result_unknown" : "executor_unavailable")); }, 40000);
      this.pending.set(requestId, { resolve, reject, timer, action, recoveryKey });
    });
    const message = { protocol: PROTOCOL, kind: "request", channel: this.channel, request_id: requestId, action,
      source: { source_id: source.source_id, binding_sha256: source.access!.binding_sha256, ...(configSha ? {config_sha256: configSha} : {}) },
      ...(routeKey ? { route_key: routeKey } : {}), ...(action === "configure" && setupMethod ? { setup_method: setupMethod } : {}) };
    if (this.port) this.port.postMessage(message); else window.parent.postMessage(message, this.origin);
    return promise;
  }
  close() {
    if (this.channel) {
      const close = { protocol: PROTOCOL, kind: "close", channel: this.channel };
      if (this.port) this.port.postMessage(close); else if (this.origin) window.parent.postMessage(close, this.origin);
    }
    this.closed = true; this.activityListeners.clear();this.observed.clear(); this.port?.close(); window.removeEventListener("message", this.receive); window.clearTimeout(this.readyTimer);
    this.readyReject?.(new Error("source_host_closed"));
    for (const item of this.pending.values()) { window.clearTimeout(item.timer); item.reject(new Error("source_host_closed")); }
    this.pending.clear();
  }
}
