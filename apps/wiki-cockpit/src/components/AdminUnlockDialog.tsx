// AdminUnlockDialog (god-mode plan §13.1, PR3): challenge -> code -> unlock.
//
// The dialog never sees the token: unlockAdminSession() stores it directly in
// the in-memory session store. What the operator types here is the ONE-TIME
// code printed on the local process terminal — a proof of presence, not a
// password (plan §7.1). Every failed attempt consumes its challenge, so the
// dialog transparently requests a fresh one before the next try. Reloading
// the page locks again by construction (nothing is persisted anywhere).

import { useCallback, useEffect, useRef, useState } from "react";
import { KeyRound, X } from "lucide-react";
import { t } from "../data/i18n";
import type { AdminPort } from "../application/ports";
import type { AdminSessionErrorCode } from "../data/admin";
import type { AdminSessionDescription } from "../application/adminSession";

type DialogPhase = "preparing" | "ready" | "verifying" | "blocked";

// Terminal errors: retrying with another code cannot help; the surface
// itself is unavailable and the dialog says so instead of looping.
const TERMINAL_ERRORS: ReadonlySet<AdminSessionErrorCode> = new Set([
  "admin_disabled",
  "operator_unreachable"
]);

export function AdminUnlockDialog({
  requestAdminChallenge,
  unlockAdminSession,
  onUnlocked,
  onClose
}: {
  // Injected from the composition root — this dialog never imports transport.
  requestAdminChallenge: AdminPort["requestAdminChallenge"];
  unlockAdminSession: AdminPort["unlockAdminSession"];
  onUnlocked: (session: AdminSessionDescription) => void;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<DialogPhase>("preparing");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [errorCode, setErrorCode] = useState<AdminSessionErrorCode | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  const fetchChallenge = useCallback(async () => {
    setPhase("preparing");
    const result = await requestAdminChallenge();
    if (result.ok) {
      setChallenge(result.challenge);
      setPhase("ready");
      return;
    }
    setChallenge(null);
    setErrorCode(result.errorCode);
    setPhase(TERMINAL_ERRORS.has(result.errorCode) ? "blocked" : "ready");
  }, [requestAdminChallenge]);

  useEffect(() => {
    void fetchChallenge();
  }, [fetchChallenge]);

  // Focus management (plan §23): the code input as soon as it exists,
  // otherwise the close control — focus never stays behind the dialog.
  useEffect(() => {
    if (phase === "ready" && challenge) {
      inputRef.current?.focus();
    } else if (phase === "blocked") {
      closeRef.current?.focus();
    }
  }, [phase, challenge]);

  const submit = async () => {
    if (!challenge || phase === "verifying" || !code.trim()) return;
    setPhase("verifying");
    setErrorCode(null);
    const result = await unlockAdminSession(challenge, code.trim());
    if (result.ok) {
      setCode("");
      onUnlocked(result.session);
      return;
    }
    setErrorCode(result.errorCode);
    setChallenge(null);
    setCode("");
    if (TERMINAL_ERRORS.has(result.errorCode) || result.errorCode === "admin_rate_limited") {
      setPhase("blocked");
      return;
    }
    // The used challenge is gone either way — arm a fresh one for the retry.
    await fetchChallenge();
  };

  return (
    <div
      className="adminUnlockOverlay"
      role="presentation"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <div className="adminUnlockDialog" role="dialog" aria-modal="true" aria-label={t("admin.unlock.title")}>
        <header className="dockHeader">
          <KeyRound size={16} aria-hidden />
          <strong>{t("admin.unlock.title")}</strong>
          <button
            className="readerClose"
            onClick={onClose}
            title={t("surface.close")}
            aria-label={t("surface.close")}
            type="button"
            ref={closeRef}
          >
            <X size={16} />
          </button>
        </header>
        <p className="adminUnlockIntro">{t("admin.unlock.intro")}</p>
        {phase === "preparing" && <p role="status">{t("admin.unlock.preparing")}</p>}
        {errorCode && (
          <p className="adminUnlockError" role="alert">
            {t(`admin.unlock.error.${errorCode}`)}
          </p>
        )}
        {phase !== "blocked" && (
          <form
            className="adminUnlockForm"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <label htmlFor="adminUnlockCode">{t("admin.unlock.codeLabel")}</label>
            <input
              id="adminUnlockCode"
              ref={inputRef}
              type="text"
              inputMode="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder={t("admin.unlock.placeholder")}
              value={code}
              disabled={phase !== "ready" || !challenge}
              onChange={(event) => setCode(event.target.value)}
            />
            <div className="dockActions">
              <button
                className="primaryButton"
                type="submit"
                disabled={phase !== "ready" || !challenge || !code.trim()}
              >
                {phase === "verifying" ? t("admin.unlock.verifying") : t("admin.unlock.submit")}
              </button>
              <button className="secondaryButton" type="button" onClick={onClose}>
                {t("admin.unlock.cancel")}
              </button>
            </div>
          </form>
        )}
        {phase === "blocked" && (
          <div className="dockActions">
            <button className="secondaryButton" type="button" onClick={() => void fetchChallenge()}>
              {t("admin.unlock.retry")}
            </button>
            <button className="secondaryButton" type="button" onClick={onClose}>
              {t("admin.unlock.cancel")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
