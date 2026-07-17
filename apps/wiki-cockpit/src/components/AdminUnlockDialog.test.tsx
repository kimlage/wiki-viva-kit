// @vitest-environment jsdom

// AdminUnlockDialog (plan §13.1, §22.2): challenge on mount, typed errors,
// a fresh challenge after every failed attempt (they are single-use), and a
// terminal "blocked" state for rate limiting — never a falsely hopeful form.

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { configureLanguage, t } from "../data/i18n";

const { requestAdminChallenge, unlockAdminSession } = vi.hoisted(() => ({
  requestAdminChallenge: vi.fn(async (): Promise<unknown> => ({ ok: true, challenge: "ch-1" })),
  unlockAdminSession: vi.fn(async (): Promise<unknown> => ({ ok: false, errorCode: "admin_unlock_code_rejected" }))
}));

vi.mock("../data/admin", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data/admin")>()),
  requestAdminChallenge,
  unlockAdminSession
}));

import { AdminUnlockDialog } from "./AdminUnlockDialog";

const session = {
  sessionId: "session_1",
  role: "admin",
  state: "active_full",
  expiresAtMs: 1_000_000,
  ttlS: 900,
  idleLockS: 300
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  requestAdminChallenge.mockResolvedValue({ ok: true, challenge: "ch-1" });
  configureLanguage("en");
});

async function typeAndSubmit(code: string) {
  const input = await screen.findByLabelText(t("admin.unlock.codeLabel"));
  fireEvent.change(input, { target: { value: code } });
  fireEvent.click(screen.getByText(t("admin.unlock.submit")));
}

describe("AdminUnlockDialog", () => {
  it("requests a challenge on mount and unlocks with the typed code", async () => {
    unlockAdminSession.mockResolvedValue({ ok: true, session });
    const onUnlocked = vi.fn();
    render(<AdminUnlockDialog onUnlocked={onUnlocked} onClose={() => {}} />);
    await waitFor(() => expect(requestAdminChallenge).toHaveBeenCalledTimes(1));
    await typeAndSubmit("AAAA-2222");
    await waitFor(() => expect(onUnlocked).toHaveBeenCalledWith(session));
    expect(unlockAdminSession).toHaveBeenCalledWith("ch-1", "AAAA-2222");
  });

  it("shows the typed error for a wrong code and arms a FRESH challenge", async () => {
    unlockAdminSession.mockResolvedValue({ ok: false, errorCode: "admin_unlock_code_rejected" });
    const onUnlocked = vi.fn();
    render(<AdminUnlockDialog onUnlocked={onUnlocked} onClose={() => {}} />);
    await typeAndSubmit("WRNG-CODE");
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        t("admin.unlock.error.admin_unlock_code_rejected")
      )
    );
    expect(onUnlocked).not.toHaveBeenCalled();
    // The consumed challenge was replaced so the next try can succeed.
    expect(requestAdminChallenge).toHaveBeenCalledTimes(2);
  });

  it("turns rate limiting into a blocked state with only retry/cancel", async () => {
    unlockAdminSession.mockResolvedValue({ ok: false, errorCode: "admin_rate_limited" });
    render(<AdminUnlockDialog onUnlocked={() => {}} onClose={() => {}} />);
    await typeAndSubmit("AAAA-2222");
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        t("admin.unlock.error.admin_rate_limited")
      )
    );
    expect(screen.queryByLabelText(t("admin.unlock.codeLabel"))).toBeNull();
    expect(screen.getByText(t("admin.unlock.retry"))).toBeTruthy();
  });

  it("reports an unreachable operator without pretending a form could help", async () => {
    requestAdminChallenge.mockResolvedValue({ ok: false, errorCode: "operator_unreachable" });
    render(<AdminUnlockDialog onUnlocked={() => {}} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe(
        t("admin.unlock.error.operator_unreachable")
      )
    );
  });

  it("closes on Escape (ladder respected: stopPropagation keeps the dock open)", async () => {
    const onClose = vi.fn();
    render(<AdminUnlockDialog onUnlocked={() => {}} onClose={onClose} />);
    const input = await screen.findByLabelText(t("admin.unlock.codeLabel"));
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
