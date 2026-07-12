import { apiUrl } from "../../data/runtimeConfig";
import {
  operatorRestartReason,
  validateOperatorHandshake
} from "../../contracts/operatorSecurity.js";
import type { OperatorHealth } from "../../types";

type OperatorSecurity = NonNullable<OperatorHealth["operator_security"]>;
type SecurityCache = { healthUrl: string; security: OperatorSecurity };

let securityCache: SecurityCache | null = null;
let securityRequest: Promise<SecurityCache> | null = null;
let fallbackAttemptCounter = 0;

export function demoRouteRequested(): boolean {
  const pathname = globalThis.location?.pathname ?? "";
  const search = globalThis.location?.search ?? "";
  return (
    pathname === "/demo" ||
    pathname.startsWith("/demo/") ||
    new URLSearchParams(search).get("demo") === "1"
  );
}

export function assertOperatorRoute(): void {
  if (demoRouteRequested()) {
    throw new Error("read-only demo blocked a local-operator request");
  }
}

function assertSignal(signal?: AbortSignal): void {
  if (!signal?.aborted) return;
  throw signal.reason instanceof Error
    ? signal.reason
    : new DOMException("The operation was aborted", "AbortError");
}

// The single transport boundary for every local-operator read and mutation.
// Route/config resolution can yield, so check both before and after apiUrl(),
// then once more at the exact point fetch (and any browser OPTIONS preflight)
// can leave the page.
export async function operatorRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const signal = init.signal ?? undefined;
  assertOperatorRoute();
  assertSignal(signal);
  const url = await apiUrl(path);
  assertOperatorRoute();
  assertSignal(signal);
  return operatorRequestUrl(url, init);
}

// Live snapshot/static-sidecar reads can already have a fully resolved URL.
// They still cross the same route boundary immediately before transport.
export function operatorRequestUrl(url: string, init: RequestInit = {}): Promise<Response> {
  const signal = init.signal ?? undefined;
  assertOperatorRoute();
  assertSignal(signal);
  return fetch(url, init);
}

function staleOperatorError(health: OperatorHealth): Error {
  return new Error(operatorRestartReason(validateOperatorHandshake(health)));
}

async function requestHealth(signal?: AbortSignal): Promise<{
  healthUrl: string;
  health: OperatorHealth;
  validation: ReturnType<typeof validateOperatorHandshake>;
}> {
  const response = await operatorRequest("/health", {
    method: "GET",
    headers: { accept: "application/json" },
    cache: "no-store",
    signal
  });
  const healthUrl = response.url || await apiUrl("/health");
  assertOperatorRoute();
  assertSignal(signal);
  if (!response.ok) throw new Error(`operator handshake failed: ${response.status}`);
  const health = (await response.json()) as OperatorHealth;
  if (!health.ok) throw new Error("operator handshake returned an unhealthy operator");
  const validation = validateOperatorHandshake(health);
  if (validation.ok) securityCache = { healthUrl, security: validation.security };
  return { healthUrl, health, validation };
}

async function securityForMutation(force = false, signal?: AbortSignal): Promise<SecurityCache> {
  assertOperatorRoute();
  assertSignal(signal);
  if (!force && securityCache) return securityCache;
  // A caller-owned signal must never cancel another caller's shared
  // handshake. Only unsignalled requests share the in-flight probe.
  if (!force && !signal && securityRequest) return securityRequest;
  const request = requestHealth(signal).then(({ healthUrl: resolvedUrl, health, validation }) => {
    assertOperatorRoute();
    assertSignal(signal);
    if (!validation.ok) {
      throw staleOperatorError(health);
    }
    return { healthUrl: resolvedUrl, security: validation.security };
  });
  if (!signal) securityRequest = request;
  try {
    return await request;
  } finally {
    if (securityRequest === request) securityRequest = null;
  }
}

function attemptKey(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return `wiki-${globalThis.crypto.randomUUID()}`;
  fallbackAttemptCounter += 1;
  return `wiki-${Date.now().toString(36)}-${fallbackAttemptCounter.toString(36).padStart(4, "0")}`;
}

async function send(
  path: string,
  body: string,
  key: string,
  security: OperatorSecurity,
  signal?: AbortSignal
): Promise<Response> {
  if (new TextEncoder().encode(body).byteLength > security.max_body_bytes) {
    throw new Error(`operator request exceeds the advertised ${security.max_body_bytes} byte limit`);
  }
  return operatorRequest(path, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      [security.nonce_header]: security.nonce,
      [security.attempt_header]: key
    },
    body,
    signal
  });
}

// One logical mutation owns one stable attempt key. A 403 commonly means the
// local operator restarted and rotated its nonce; re-handshake once and retry
// with the SAME key so the server can replay rather than duplicate work.
export async function operatorPost(
  path: string,
  payload: unknown,
  options: { signal?: AbortSignal } = {}
): Promise<Response> {
  // The UI disables every write affordance under /demo, but this boundary is
  // the final fail-closed guarantee: a missed handler, synthetic click or new
  // surface still cannot even handshake with the local operator, let alone
  // emit a POST. Genesis advances via staged browser-local snapshots only.
  assertOperatorRoute();
  assertSignal(options.signal);
  const body = JSON.stringify(payload ?? {});
  const key = attemptKey();
  let security = await securityForMutation(false, options.signal);
  assertOperatorRoute();
  assertSignal(options.signal);
  let response = await send(path, body, key, security.security, options.signal);
  if (response.status !== 403) return response;
  securityCache = null;
  // Do not even re-handshake after the first attempt if navigation crossed the
  // read-only boundary while that request was in flight.
  assertOperatorRoute();
  assertSignal(options.signal);
  security = await securityForMutation(true, options.signal);
  assertOperatorRoute();
  assertSignal(options.signal);
  response = await send(path, body, key, security.security, options.signal);
  return response;
}

export async function fetchOperatorHealth(options: { signal?: AbortSignal } = {}): Promise<OperatorHealth | null> {
  try {
    return (await requestHealth(options.signal)).health;
  } catch {
    return null;
  }
}

export function resetOperatorSecurityForTests(): void {
  securityCache = null;
  securityRequest = null;
  fallbackAttemptCounter = 0;
}
