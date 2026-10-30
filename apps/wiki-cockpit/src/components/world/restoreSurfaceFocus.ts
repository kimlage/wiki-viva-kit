/** Restore a dismissed surface's invoker without overriding a newer focus intent. */
export function restoreSurfaceFocus(opener: HTMLElement | null, fallback: HTMLElement | null): void {
  const unavailable = '[inert], [aria-hidden="true"], [hidden]';
  const active = document.activeElement;
  // Restoration runs after an exit animation/frame. A user may already have
  // focused the search or another live control; that newer intent owns focus.
  if (active && active !== document.body && active !== document.documentElement &&
      active.isConnected && !active.closest(unavailable)) return;
  const target = opener?.isConnected && !opener.closest(unavailable) ? opener : fallback;
  if (target?.isConnected && !target.closest(unavailable)) target.focus({ preventScroll: true });
}
