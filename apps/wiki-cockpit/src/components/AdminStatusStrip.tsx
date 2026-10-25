// AdminStatusStrip (god-mode plan §14.4, §5.4): the persistent, text-first
// indicator that an administrative session exists. Never color-only — the
// state and the remaining time are words, with ARIA labels, plus an
// ever-visible "Lock now" button. Absence means no local credential; only
// positive native readback proves admitted effects drained. Takezo is never the only signal
// (anti-pattern 13).
//
// The countdown is presentation math over one wall-clock deadline captured
// at unlock/renew; the server's own TTL/idle lock stays authoritative. When
// the local countdown reaches zero the strip removes command access and
// retains RAM-only confirmation instead of assuming admitted effects ended.

import { useEffect, useState, useSyncExternalStore } from "react";
import { KeyRound, Lock, RefreshCw } from "lucide-react";
import { t } from "../data/i18n";
import {
  adminSessionRemainingS,
  adminLockNoticeKey,
  beginAdminSessionRevocation,
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
    if (!session || session.revocationState) return;
    if (getAdminSessionDescription() !== session) return;
    if (adminSessionRemainingS(nowMs) > 0) return;
    // Local time is not proof of native drain. A stale timer cannot revoke
    // a newer session installed since this render.
    beginAdminSessionRevocation("unconfirmed");
    onNotice?.(t("admin.strip.expiredPending"));
  }, [session, nowMs, onNotice]);

  if (!session) return null;

  const remainingS = adminSessionRemainingS(nowMs);
  if (remainingS <= 0 && !session.revocationState) return null;
  const remainingMin = Math.ceil(remainingS / 60);
  const displayState = session.revocationState ? "revocation_pending" : remainingS <= 120 ? "expiring" : session.state;
  const stateLabel = t(session.revocationState ? "admin.state.revocationPending"
    : STATE_LABEL_KEYS[displayState] || "admin.state.active_partial");
  const timeLabel =
    session.revocationState ? t("admin.strip.completionUnconfirmed") : remainingS < 60
      ? t("admin.strip.timeLeftUnderMinute")
      : t("admin.strip.timeLeft", { m: remainingMin });

  const renew = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await renewAdminSession();
      if (!result.ok && result.errorCode === "admin_response_superseded") return;
      onNotice?.(result.ok ? t("admin.strip.renewed") : t("admin.strip.renewFailed"));
    } finally {
      setBusy(false);
    }
  };

  const lock = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await lockAdminSession();
      const notice = adminLockNoticeKey(result);
      if (notice) onNotice?.(t(notice));
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
        disabled={busy || !!session.revocationState}
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
        title={t(session.revocationState ? "admin.strip.confirmLock" : "admin.strip.lock")}
      >
        <Lock size={13} aria-hidden />
        <span>{t(session.revocationState ? "admin.strip.confirmLock" : "admin.strip.lock")}</span>
      </button>
    </div>
  );
}
