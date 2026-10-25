// @vitest-environment jsdom

// AdminStatusStrip (plan §14.4, §22.2): invisible while locked, text-first
// state + remaining time while active, an always-available lock button, and
// a local expiry that clears the session instead of showing a false active.

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage, t } from "../data/i18n";
import { clearAdminSession, setAdminSession, beginAdminSessionRevocation, getAdminSessionToken } from "../application/adminSession";

const { lockAdminSession, renewAdminSession } = vi.hoisted(() => ({
  lockAdminSession: vi.fn(async (): Promise<unknown> => ({ ok: true })),
  renewAdminSession: vi.fn(async (): Promise<unknown> => ({ ok: false, errorCode: "admin_session_expired" }))
}));

import { AdminStatusStrip } from "./AdminStatusStrip";
import type { AdminPort } from "../application/ports";

// The strip takes its transport as injected props (composition root); the
// tests hand it these fakes — no module mocking, no network anywhere.
const sessionPorts = {
  lockAdminSession: lockAdminSession as AdminPort["lockAdminSession"],
  renewAdminSession: renewAdminSession as AdminPort["renewAdminSession"]
};

function activate(expiresInMs: number, state = "active_full") {
  setAdminSession("tok-strip", {
    sessionId: "session_strip",
    role: "admin",
    state,
    expiresAtMs: Date.now() + expiresInMs,
    ttlS: 900,
    idleLockS: 300
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  clearAdminSession();
  configureLanguage("en");
});

describe("AdminStatusStrip", () => {
  it("renders nothing while locked — absence IS the locked indicator", () => {
    const { container } = render(<AdminStatusStrip {...sessionPorts} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the state and remaining time as text with a lock button (§14.4)", () => {
    activate(10 * 60 * 1000);
    render(<AdminStatusStrip {...sessionPorts} />);
    expect(screen.getByText(t("admin.state.active_full"))).toBeTruthy();
    expect(screen.getByText(t("admin.strip.timeLeft", { m: 10 }))).toBeTruthy();
    expect(screen.getByText(t("admin.strip.lock"))).toBeTruthy();
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("switches to the expiring label under the threshold", () => {
    activate(90 * 1000);
    render(<AdminStatusStrip {...sessionPorts} />);
    expect(screen.getByText(t("admin.state.expiring"))).toBeTruthy();
  });

  it("locks on demand and reports it (§5.4)", async () => {
    activate(10 * 60 * 1000);
    lockAdminSession.mockImplementation(async () => {
      clearAdminSession(); // the real client always forgets the token
      return { ok: true };
    });
    const onNotice = vi.fn();
    render(<AdminStatusStrip {...sessionPorts} onNotice={onNotice} />);
    fireEvent.click(screen.getByText(t("admin.strip.lock")));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(t("admin.strip.locked")));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("local expiry removes command access but preserves confirmation until native drain", async () => {
    activate(-1000);
    const onNotice = vi.fn();
    const { container } = render(<AdminStatusStrip {...sessionPorts} onNotice={onNotice} />);
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(t("admin.strip.expiredPending")));
    expect(getAdminSessionToken()).toBeNull();
    expect(container.querySelector(".adminStatusStrip")).toBeTruthy();
    expect((screen.getByRole("button", { name: t("admin.strip.renew") }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: t("admin.strip.confirmLock") })).toBeTruthy();
  });

  it("pending revocation survives reopening and never announces a completed lock", async () => {
    activate(10 * 60 * 1000);
    lockAdminSession.mockImplementationOnce(async () => {
      beginAdminSessionRevocation("pending");
      return { ok: false, errorCode: "admin_revocation_pending" };
    });
    const onNotice = vi.fn();
    const first = render(<AdminStatusStrip {...sessionPorts} onNotice={onNotice} />);
    fireEvent.click(screen.getByRole("button", { name: t("admin.strip.lock") }));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(t("admin.strip.revocationPending")));
    expect(onNotice).not.toHaveBeenCalledWith(t("admin.strip.locked"));
    first.unmount();
    render(<AdminStatusStrip {...sessionPorts} onNotice={onNotice} />);
    lockAdminSession.mockImplementationOnce(async () => { clearAdminSession(); return { ok: true }; });
    fireEvent.click(screen.getByRole("button", { name: t("admin.strip.confirmLock") }));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(t("admin.strip.locked")));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renews through the client and reports the rotation", async () => {
    activate(10 * 60 * 1000);
    renewAdminSession.mockResolvedValue({ ok: true, session: {} });
    const onNotice = vi.fn();
    render(<AdminStatusStrip {...sessionPorts} onNotice={onNotice} />);
    fireEvent.click(screen.getByText(t("admin.strip.renew")));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith(t("admin.strip.renewed")));
    expect(renewAdminSession).toHaveBeenCalledTimes(1);
  });

  it("does not announce a superseded renewal as failure of the current session", async () => {
    activate(10 * 60 * 1000);
    renewAdminSession.mockResolvedValueOnce({ok:false,errorCode:"admin_response_superseded"});
    const onNotice=vi.fn();
    render(<AdminStatusStrip {...sessionPorts} onNotice={onNotice} />);
    fireEvent.click(screen.getByRole("button",{name:t("admin.strip.renew")}));
    await waitFor(() => expect(renewAdminSession).toHaveBeenCalled());
    expect(onNotice).not.toHaveBeenCalled();
  });
});
