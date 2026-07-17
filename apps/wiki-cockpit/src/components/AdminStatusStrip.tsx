// AdminStatusStrip (god-mode plan §14.4, §5.4): the persistent, text-first
// indicator that an administrative session exists. Never color-only — the
// state and the remaining time are words, with ARIA labels, plus an
// ever-visible "Lock now" button. It renders nothing while locked: absence
// of the strip IS the locked indicator, and Takezo is never the only signal
// (anti-pattern 13).
//
// The countdown is presentation math over one wall-clock deadline captured
// at unlock/renew; the server's own TTL/idle lock stays authoritative. When
// the local countdown reaches zero the strip clears the in-memory session
// (the server already considers it dead) instead of showing a false active.

import { useEffect, useState, useSyncExternalStore } from "react";
import { KeyRound, Lock, RefreshCw } from "lucide-react";
import { t } from "../data/i18n";
import {
  adminSessionRemainingS,
  clearAdminSession,
  getAdminSessionDescription,
  subscribeAdminSession
} from "../application/adminSession";
import type { AdminPort } from "../application/ports";

const TICK_MS = 15_000;

const STATE_LABEL_KEYS: Record<string, string> = {
  active_readonly: "admin.state.active_readonly",
  active_partial: "admin.state.active_partial",
  active_full: "admin.state.active_full",
  expiring: "admin.state.expiring"
};

export function AdminStatusStrip({
  lockAdminSession,
  renewAdminSession,
  onNotice,
  onOpenDock
}: {
  // Injected from the composition root — the strip never imports transport.
  lockAdminSession: AdminPort["lockAdminSession"];
  renewAdminSession: AdminPort["renewAdminSession"];
  onNotice?: (text: string) => void;
  onOpenDock?: () => void;
}) {
  const session = useSyncExternalStore(subscribeAdminSession, getAdminSessionDescription);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!session) return undefined;
    setNowMs(Date.now());
    const timer = setInterval(() => setNowMs(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, [session]);

  useEffect(() => {
    if (!session) return;
    if (adminSessionRemainingS(nowMs) > 0) return;
    // The deadline passed: the server already expired this session. Clear
    // the client side and say so — never a silently "active" chip (§22.2).
    clearAdminSession();
    onNotice?.(t("admin.strip.expired"));
  }, [session, nowMs, onNotice]);

  if (!session) return null;

  const remainingS = adminSessionRemainingS(nowMs);
  if (remainingS <= 0) return null;
  const remainingMin = Math.ceil(remainingS / 60);
  const displayState = remainingS <= 120 ? "expiring" : session.state;
  const stateLabel = t(STATE_LABEL_KEYS[displayState] || "admin.state.active_partial");
  const timeLabel =
    remainingS < 60
      ? t("admin.strip.timeLeftUnderMinute")
      : t("admin.strip.timeLeft", { m: remainingMin });

  const renew = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await renewAdminSession();
      onNotice?.(result.ok ? t("admin.strip.renewed") : t("admin.strip.renewFailed"));
    } finally {
      setBusy(false);
    }
  };

  const lock = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await lockAdminSession();
      // lockAdminSession always clears the in-memory token (§5.4); the strip
      // unmounts via the store subscription right after this notice.
      onNotice?.(t("admin.strip.locked"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={`adminStatusStrip adminStrip-${displayState}`}
      role="status"
      aria-label={t("admin.strip.aria", { state: stateLabel, time: timeLabel })}
    >
      {onOpenDock ? (
        <button
          className="adminStripState"
          type="button"
          onClick={onOpenDock}
          title={t("admin.strip.openDock")}
        >
          <KeyRound size={13} aria-hidden />
          <span>{stateLabel}</span>
        </button>
      ) : (
        <span className="adminStripState">
          <KeyRound size={13} aria-hidden />
          <span>{stateLabel}</span>
        </span>
      )}
      <span className="adminStripTime">{timeLabel}</span>
      <button
        className="adminStripAction"
        type="button"
        onClick={() => void renew()}
        disabled={busy}
        title={t("admin.strip.renew")}
      >
        <RefreshCw size={13} aria-hidden />
        <span>{t("admin.strip.renew")}</span>
      </button>
      <button
        className="adminStripAction adminStripLock"
        type="button"
        onClick={() => void lock()}
        disabled={busy}
        title={t("admin.strip.lock")}
      >
        <Lock size={13} aria-hidden />
        <span>{t("admin.strip.lock")}</span>
      </button>
    </div>
  );
}
