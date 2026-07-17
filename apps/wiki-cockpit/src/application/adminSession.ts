// In-memory admin session state (god-mode plan §13.2, §22.2).
//
// The token lives EXCLUSIVELY in this module's closure: never in the URL,
// never in localStorage/sessionStorage/IndexedDB/cookies, never in the
// snapshot. A page reload therefore locks by construction — there is
// nothing to rehydrate from. The token itself is deliberately NOT part of
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
};

type Listener = () => void;

let sessionToken: string | null = null;
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
  sessionDescription = description;
  emit();
}

/** Forget everything (lock, expiry, server-side revocation, failure). */
export function clearAdminSession(): void {
  const hadSession = sessionToken !== null || sessionDescription !== null;
  sessionToken = null;
  sessionDescription = null;
  if (hadSession) emit();
}

/** Transport-only accessor: the header value for the next admin request. */
export function getAdminSessionToken(): string | null {
  return sessionToken;
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
