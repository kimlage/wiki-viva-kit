// In-memory session store (plan §13.2, §22.2): the token exists only in the
// module closure, listeners hear every transition, and the countdown is pure
// presentation math over the captured deadline.

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  adminSessionActive,
  adminSessionRemainingS,
  clearAdminSession,
  getAdminSessionDescription,
  getAdminSessionToken,
  setAdminSession,
  subscribeAdminSession
} from "./adminSession";

function description(expiresAtMs: number) {
  return {
    sessionId: "session_1",
    role: "admin",
    state: "active_full",
    expiresAtMs,
    ttlS: 900,
    idleLockS: 300
  };
}

afterEach(() => {
  clearAdminSession();
});

describe("adminSession store", () => {
  it("starts locked and exposes no token or description", () => {
    expect(adminSessionActive()).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
    expect(getAdminSessionDescription()).toBeNull();
    expect(adminSessionRemainingS(0)).toBe(0);
  });

  it("keeps the token separate from the public description", () => {
    setAdminSession("tok-1", description(60_000));
    expect(adminSessionActive()).toBe(true);
    expect(getAdminSessionToken()).toBe("tok-1");
    // The description object carries no token-shaped field at all.
    expect(JSON.stringify(getAdminSessionDescription())).not.toContain("tok-1");
  });

  it("computes remaining seconds from the captured deadline, clamped at zero", () => {
    setAdminSession("tok-1", description(120_000));
    expect(adminSessionRemainingS(0)).toBe(120);
    expect(adminSessionRemainingS(119_000)).toBe(1);
    expect(adminSessionRemainingS(120_000)).toBe(0);
    expect(adminSessionRemainingS(999_000)).toBe(0);
  });

  it("notifies subscribers on set and on clear, and unsubscribes cleanly", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeAdminSession(listener);
    setAdminSession("tok-1", description(60_000));
    expect(listener).toHaveBeenCalledTimes(1);
    clearAdminSession();
    expect(listener).toHaveBeenCalledTimes(2);
    // Clearing an already-locked store is silent (no phantom transitions).
    clearAdminSession();
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setAdminSession("tok-2", description(60_000));
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("clear wipes both token and description (reload-equivalent lock)", () => {
    setAdminSession("tok-1", description(60_000));
    clearAdminSession();
    expect(adminSessionActive()).toBe(false);
    expect(getAdminSessionToken()).toBeNull();
    expect(getAdminSessionDescription()).toBeNull();
  });
});
