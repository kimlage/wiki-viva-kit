// AdminDock (?dock=admin): the READ-ONLY god-mode surface (plan §14, PR2).
// It renders exactly what the operator's discovery endpoint answers — session
// state, capability chips, versions, snapshot age — and can change nothing:
// there is no mutation affordance in this component and no session subsystem
// behind it yet. Opening the dock (typed command, ritual gate or raw
// ?dock=admin URL) NEVER authorizes anything (plan §14.1): the URL is just a
// place, the server owns the state.

import { useEffect, useState } from "react";
import { KeyRound, RefreshCw, X } from "lucide-react";
import { t } from "../data/i18n";
import { loadAdminAccess } from "../data/admin";
import type { AdminAccess, AdminSessionState } from "../data/admin";
import {
  REQUIRED_OPERATOR_SERVER_VERSION
} from "../contracts/operatorSecurity.js";
import type { SnapshotBundle } from "../types";

// §6.3: never color-only — every state is a text label with its own key.
const STATE_LABEL_KEYS: Record<AdminSessionState, string> = {
  unavailable: "admin.state.unavailable",
  locked: "admin.state.locked",
  unlocking: "admin.state.unlocking",
  active_readonly: "admin.state.active_readonly",
  active_partial: "admin.state.active_partial",
  active_full: "admin.state.active_full",
  expiring: "admin.state.expiring",
  revoked: "admin.state.revoked"
};

// Deterministic timestamp label (same shape as the world HUD) — the dock
// never computes a relative age from the wall clock.
function generatedLabel(value: string): string {
  if (!value) return t("misc.noDate");
  return value.replace("T", " ").replace("Z", "").slice(0, 16);
}

function reasonLabel(reason: string | undefined): string | null {
  if (!reason) return null;
  const key = `admin.capabilityReason.${reason}`;
  const resolved = t(key);
  return resolved === key ? reason : resolved;
}

export function AdminDock({
  bundle,
  demo,
  runtimeMode,
  onClose
}: {
  bundle: SnapshotBundle;
  demo: boolean;
  runtimeMode: string;
  onClose: () => void;
}) {
  const [access, setAccess] = useState<AdminAccess | null>(null);
  const [probe, setProbe] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // The sealed demo never even attempts an operator request (loadAdminAccess
    // guards the route too; this early state keeps the intent visible here).
    if (demo) {
      setAccess({ kind: "unavailable", reason: "demo" });
      return () => undefined;
    }
    setAccess(null);
    loadAdminAccess()
      .then((result) => {
        if (!cancelled) setAccess(result);
      })
      .catch(() => {
        if (!cancelled) setAccess({ kind: "unavailable", reason: "operator_unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, [demo, probe]);

  const payload = access?.kind === "capabilities" ? access.payload : null;
  const state: AdminSessionState = payload ? payload.session_state : "unavailable";
  const stateLabel = access === null ? t("admin.state.loading") : t(STATE_LABEL_KEYS[state]);
  const granted = payload ? payload.capabilities.filter((entry) => entry.granted).length : 0;
  const total = payload ? payload.capabilities.length : 0;

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="adminDock worldDock" role="dialog" aria-label={t("admin.dock.title")}>
        <header className="dockHeader">
          <KeyRound size={16} aria-hidden />
          <strong>{t("admin.dock.title")}</strong>
          <span className={`pill pill-muted adminStateChip adminState-${access === null ? "loading" : state}`}>
            {stateLabel}
          </span>
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("admin.dock.readOnlyNote")}</p>

        <section className="adminSection" aria-label={t("admin.section.overview")}>
          <h3>{t("admin.section.overview")}</h3>
          {access === null && <p role="status">{t("admin.state.loadingBody")}</p>}
          {access?.kind === "unavailable" && (
            <>
              <p>{t(`admin.reason.${access.reason}`)}</p>
              {access.detail && (
                <p className="adminDetail">
                  <code>{access.detail}</code>
                </p>
              )}
            </>
          )}
          {payload && (
            <>
              <p>
                {state === "locked" && t("admin.locked.note")}
                {state === "active_readonly" && t("admin.readonly.note")}
                {state !== "locked" && state !== "active_readonly" && t("admin.overview.sessionState", { state: stateLabel })}
              </p>
              <p>{t("admin.overview.capabilities", { granted, total })}</p>
              <ul className="adminCapabilityChips" aria-label={t("admin.overview.capabilitiesAria")}>
                {payload.capabilities.map((entry) => {
                  const reason = reasonLabel(entry.reason);
                  const stateText = entry.granted
                    ? t("admin.capability.granted")
                    : t("admin.capability.notGranted");
                  return (
                    <li
                      key={entry.id}
                      className={entry.granted ? "adminCapability granted" : "adminCapability absent"}
                      title={reason ? `${stateText} — ${reason}` : stateText}
                    >
                      <code>{entry.id}</code>
                      <small>{stateText}</small>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          <dl className="adminFacts">
            <div>
              <dt>{t("admin.overview.runtime")}</dt>
              <dd>{demo ? t("world.demoMode") : runtimeMode || t("misc.noDate")}</dd>
            </div>
            <div>
              <dt>{t("admin.overview.snapshot")}</dt>
              <dd>
                {t("admin.overview.snapshotAge", { when: generatedLabel(bundle.manifest.generated_at) })}
                {bundle.manifest.snapshot_id ? <code> {bundle.manifest.snapshot_id}</code> : null}
              </dd>
            </div>
          </dl>
        </section>

        <section className="adminSection" aria-label={t("admin.section.system")}>
          <h3>{t("admin.section.system")}</h3>
          <dl className="adminFacts">
            <div>
              <dt>{t("admin.system.repo")}</dt>
              <dd>{bundle.manifest.repo.repo_id}</dd>
            </div>
            <div>
              <dt>{t("admin.system.branch")}</dt>
              <dd>
                {bundle.git.current_branch ? <code>{bundle.git.current_branch}</code> : t("admin.system.branchUnknown")}
                {bundle.git.default_branch ? ` → ${bundle.git.default_branch}` : ""}
              </dd>
            </div>
            <div>
              <dt>{t("admin.system.worktree")}</dt>
              <dd>
                {bundle.git.worktree.clean
                  ? t("admin.system.worktreeClean")
                  : t("admin.system.worktreeChanged", { n: bundle.git.worktree.changed_files.length })}
              </dd>
            </div>
            <div>
              <dt>{t("admin.system.operator")}</dt>
              <dd>
                {payload ? (
                  <>
                    <code>{payload.server_version}</code> · <code>{payload.schema_version}</code>
                  </>
                ) : (
                  t("admin.system.operatorAbsent")
                )}
              </dd>
            </div>
            {payload?.adapter && (
              <div>
                <dt>{t("admin.system.adapter")}</dt>
                <dd>
                  <code>{payload.adapter}</code>
                </dd>
              </div>
            )}
            <div>
              <dt>{t("admin.system.versions")}</dt>
              <dd>{t("admin.system.frontendRequires", { version: REQUIRED_OPERATOR_SERVER_VERSION })}</dd>
            </div>
          </dl>
        </section>

        {!demo && (
          <div className="dockActions">
            <button
              className="secondaryButton"
              onClick={() => setProbe((value) => value + 1)}
              disabled={access === null}
              type="button"
            >
              <RefreshCw size={14} />
              <span>{t("admin.dock.refresh")}</span>
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
