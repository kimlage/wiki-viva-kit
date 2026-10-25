// In-memory admin session state (god-mode plan §13.2, §22.2).
//
// The token lives EXCLUSIVELY in this module's closure: never in the URL,
// never in localStorage/sessionStorage/IndexedDB/cookies, never in the
// snapshot. Reload removes local access; it does not prove an admitted
// operation finished. The token itself is deliberately NOT part of
// the observable snapshot; UI components subscribe to the public
// description only, and transport code asks for the token through one
// narrow accessor at send time.

export type AdminSessionDescription = {
  sessionId: string;
  role: string;
  state: string;
  // Wall-clock deadline computed once per unlock/renew from the server's
  // relative expires_in_s. The UI derives "time left" from this single
  // captured value instead of asking the server on every tick.
  expiresAtMs: number;
  ttlS: number;
  idleLockS: number;
  revocationState?: "pending" | "unconfirmed" | "uncertain";
};

type Listener = () => void;

let sessionToken: string | null = null;
let lockConfirmationToken: string | null = null;
let lifecycleGeneration = 0;
let sessionDescription: AdminSessionDescription | null = null;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of [...listeners]) listener();
}

/** Store a freshly unlocked/renewed session. Token stays module-private. */
export function setAdminSession(
  token: string,
  description: AdminSessionDescription
): void {
  sessionToken = token;
  lockConfirmationToken = null;
  sessionDescription = description;
  lifecycleGeneration += 1;
  emit();
}

/** Forget everything (lock, expiry, server-side revocation, failure). */
export function clearAdminSession(): void {
  const hadSession = sessionToken !== null || lockConfirmationToken !== null || sessionDescription !== null;
  sessionToken = null;
  lockConfirmationToken = null;
  sessionDescription = null;
  lifecycleGeneration += 1;
  if (hadSession) emit();
}

/** Transport-only accessor: the header value for the next admin request. */
export function getAdminSessionToken(): string | null {
  return sessionToken;
}

/** Immediately bar ordinary requests. Retain the credential only for lock. */
export function beginAdminSessionRevocation(
  state: NonNullable<AdminSessionDescription["revocationState"]> = "pending"
): void {
  if (sessionToken) lockConfirmationToken = sessionToken;
  sessionToken = null;
  lifecycleGeneration += 1;
  if (sessionDescription) {
    sessionDescription = { ...sessionDescription, revocationState: state };
    emit();
  }
}

/** Transport-only: this credential must never be used by command dispatch. */
export function getAdminLockConfirmationToken(): string | null {
  return lockConfirmationToken;
}

export function getAdminSessionGeneration(): number {
  return lifecycleGeneration;
}

/** A late authentication/rotation response cannot undo a requested lock. */
export function retainAdminSessionForLock(token: string, description: AdminSessionDescription): void {
  sessionToken = null;
  lockConfirmationToken = token;
  sessionDescription = { ...description, revocationState: "unconfirmed" };
  lifecycleGeneration += 1;
  emit();
}

/** Pure presentation; completion is announced only after positive readback. */
export function adminLockNoticeKey(
  result: { ok: boolean; errorCode?: string }, success = "admin.strip.locked"
): string | null {
  if (result.errorCode === "admin_response_superseded") return null;
  if (result.ok) return success;
  if (result.errorCode === "admin_revocation_pending") return "admin.strip.revocationPending";
  if (result.errorCode === "admin_effect_outcome_uncertain") return "admin.strip.effectUncertain";
  return "admin.strip.lockUnconfirmed";
}

/** Public, token-free description for UI (status strip, dock). */
export function getAdminSessionDescription(): AdminSessionDescription | null {
  return sessionDescription;
}

export function adminSessionActive(): boolean {
  return sessionToken !== null && sessionDescription !== null;
}

/**
 * Seconds left before the server-side TTL fires, from the given wall-clock
 * time. The server remains the authority — this is presentation math only.
 */
export function adminSessionRemainingS(nowMs: number): number {
  if (!sessionDescription) return 0;
  return Math.max(Math.ceil((sessionDescription.expiresAtMs - nowMs) / 1000), 0);
}

export function subscribeAdminSession(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
