// Typed-command -> Admin Dock handoff (god-mode plan §10.5, §14.1).
//
// When the operator types a bus-backed command (e.g. "> admin inspect
// system"), WorldView records the TARGET bus command here and opens the
// dock; the dock consumes the intent once and starts planning. The intent
// is pure navigation state in module memory: never in the URL (the URL
// never authorizes and never carries admin intent), never in storage, and
// consuming it grants nothing — the server still answers with its own
// session/capability truth on plan and again on execute.

type Listener = () => void;

// An intent is a fresh navigation gesture, not a standing order: if the dock
// cannot plan it within this window (e.g. it stayed locked and was closed),
// the intent silently expires instead of firing minutes later as a surprise.
// Wall-clock is fine here — this is interaction state, never build output.
const INTENT_TTL_MS = 120_000;

let pendingBusCommandId: string | null = null;
let armedAtMs = 0;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of [...listeners]) listener();
}

function expired(): boolean {
  return Date.now() - armedAtMs > INTENT_TTL_MS;
}

/** Record which bus command the Admin Dock should plan next. Subscribers are
 * notified so an ALREADY-open dock reacts too, not only a fresh mount. */
export function setAdminCommandIntent(busCommandId: string): void {
  pendingBusCommandId = busCommandId;
  armedAtMs = Date.now();
  emit();
}

/** Peek without clearing — for useSyncExternalStore snapshots. */
export function getAdminCommandIntent(): string | null {
  return pendingBusCommandId !== null && expired() ? null : pendingBusCommandId;
}

/** Read-and-clear: an intent fires at most once, even across remounts. */
export function consumeAdminCommandIntent(): string | null {
  const value = pendingBusCommandId !== null && expired() ? null : pendingBusCommandId;
  if (pendingBusCommandId !== null) {
    pendingBusCommandId = null;
    emit();
  }
  return value;
}

/** Drop a pending intent explicitly. */
export function clearAdminCommandIntent(): void {
  if (pendingBusCommandId !== null) {
    pendingBusCommandId = null;
    emit();
  }
}

export function subscribeAdminCommandIntent(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
