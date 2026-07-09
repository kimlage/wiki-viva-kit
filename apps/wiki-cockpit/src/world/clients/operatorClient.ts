import { apiUrl } from "../../data/runtimeConfig";
import type { OperatorHealth } from "../../types";

type OperatorSecurity = NonNullable<OperatorHealth["operator_security"]>;
type SecurityCache = { healthUrl: string; security: OperatorSecurity };

let securityCache: SecurityCache | null = null;
let securityRequest: Promise<SecurityCache> | null = null;
let fallbackAttemptCounter = 0;

function validSecurity(health: OperatorHealth): health is OperatorHealth & { operator_security: OperatorSecurity } {
  const security = health.operator_security;
  return Boolean(
    health.schema_capabilities?.includes("operator_security_v1") &&
      security?.version === "wiki_operator_security.v1" &&
      security.nonce &&
      security.nonce_header &&
      security.attempt_header &&
      security.mutations === "post_only"
  );
}

async function requestHealth(): Promise<{ healthUrl: string; health: OperatorHealth }> {
  const healthUrl = await apiUrl("/health");
  const response = await fetch(healthUrl, {
    method: "GET",
    headers: { accept: "application/json" },
    cache: "no-store"
  });
  if (!response.ok) throw new Error(`operator handshake failed: ${response.status}`);
  const health = (await response.json()) as OperatorHealth;
  if (!health.ok) throw new Error("operator handshake returned an unhealthy operator");
  if (validSecurity(health)) securityCache = { healthUrl, security: health.operator_security };
  return { healthUrl, health };
}

async function securityForMutation(force = false): Promise<SecurityCache> {
  const healthUrl = await apiUrl("/health");
  if (!force && securityCache?.healthUrl === healthUrl) return securityCache;
  if (!force && securityRequest) return securityRequest;
  const request = requestHealth().then(({ healthUrl: resolvedUrl, health }) => {
    if (!validSecurity(health)) {
      throw new Error("operator does not advertise the required operator_security.v1 mutation contract");
    }
    return { healthUrl: resolvedUrl, security: health.operator_security };
  });
  securityRequest = request;
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
  return fetch(await apiUrl(path), {
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
  const body = JSON.stringify(payload ?? {});
  const key = attemptKey();
  let security = await securityForMutation();
  let response = await send(path, body, key, security.security, options.signal);
  if (response.status !== 403) return response;
  securityCache = null;
  security = await securityForMutation(true);
  response = await send(path, body, key, security.security, options.signal);
  return response;
}

export async function fetchOperatorHealth(): Promise<OperatorHealth | null> {
  try {
    return (await requestHealth()).health;
  } catch {
    return null;
  }
}

export function resetOperatorSecurityForTests(): void {
  securityCache = null;
  securityRequest = null;
  fallbackAttemptCounter = 0;
}
