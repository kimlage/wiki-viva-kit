// AdminPlanReview (god-mode plan §11, §14, PR4): the review dialog between
// planning and executing one admin command. It renders EXACTLY what the
// server materialized — summary, risk, effects, diff, preconditions, undo —
// and executes by plan_id + plan_sha, so what you reviewed is what will run
// (§11.3). Confirmations follow §9.2: reads confirm nothing, a derive that
// writes carries its plan-generated phrase on the button, typed risks demand
// the exact phrase typed back. A refusal (stale plan, revoked capability,
// busy checkout) is shown as a typed message that asks for a replan — this
// dialog never retries on its own and never softens a server refusal.

import { useEffect, useRef, useState } from "react";
import { ClipboardCheck, Play, X } from "lucide-react";
import { t } from "../data/i18n";
import type { AdminPort } from "../application/ports";
import type {
  AdminCommandErrorCode,
  AdminExecuteOutcome,
  AdminPlan
} from "../data/admin";

// Errors whose only cure is a fresh plan (§9.3: refuse and replan).
const REPLAN_ERRORS: ReadonlySet<AdminCommandErrorCode> = new Set([
  "admin_plan_stale",
  "admin_plan_not_found",
  "admin_plan_sha_mismatch",
  "admin_plan_already_executed"
]);

function shortExpected(value: unknown): string {
  const text =
    typeof value === "string" ? value : JSON.stringify(value ?? null);
  return text.length > 24 ? `${text.slice(0, 24)}…` : text;
}

export function AdminPlanReview({
  executeAdminPlan,
  plan,
  onClose,
  onExecuted,
  onNotice
}: {
  // Injected from the composition root — this dialog never imports transport.
  executeAdminPlan: AdminPort["executeAdminPlan"];
  plan: AdminPlan;
  onClose: () => void;
  onExecuted?: (outcome: AdminExecuteOutcome) => void;
  onNotice?: (text: string) => void;
}) {
  const [executing, setExecuting] = useState(false);
  const [outcome, setOutcome] = useState<AdminExecuteOutcome | null>(null);
  const [error, setError] = useState<{
    code: AdminCommandErrorCode;
    failedPreconditions: string[];
  } | null>(null);
  const [typed, setTyped] = useState("");
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Focus enters the dialog on mount (plan §23) and never stays behind it.
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const confirmation = plan.confirmation;
  const typedSatisfied =
    confirmation.kind !== "typed" || typed === (confirmation.text || "");

  const execute = async () => {
    if (executing || outcome) return;
    setExecuting(true);
    setError(null);
    const supplied =
      confirmation.kind === "none"
        ? null
        : confirmation.kind === "simple"
          ? confirmation.text
          : typed;
    const result = await executeAdminPlan(plan, supplied);
    setExecuting(false);
    if (result.ok) {
      setOutcome(result.outcome);
      onExecuted?.(result.outcome);
      onNotice?.(t("admin.plan.executed"));
      return;
    }
    setError({
      code: result.errorCode,
      failedPreconditions: result.failedPreconditions ?? []
    });
  };

  const riskLabel = t(`admin.commands.risk.${plan.riskLevel}`);

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
      <div
        className="adminUnlockDialog adminPlanReview"
        role="dialog"
        aria-modal="true"
        aria-label={t("admin.plan.title", { command: plan.title })}
        tabIndex={-1}
        ref={dialogRef}
      >
        <header className="dockHeader">
          <ClipboardCheck size={16} aria-hidden />
          <strong>{t("admin.plan.title", { command: plan.title })}</strong>
          <span className={`pill pill-muted adminRisk-${plan.riskLevel}`}>{riskLabel}</span>
          {plan.dryRun && <span className="pill pill-muted">{t("admin.plan.dryRun")}</span>}
          <button
            className="readerClose"
            onClick={onClose}
            title={t("surface.close")}
            aria-label={t("surface.close")}
            type="button"
          >
            <X size={16} />
          </button>
        </header>

        {/* §11.3 — the contract line, always visible. */}
        <p className="adminPlanContract">{t("admin.plan.contract")}</p>
        <p className="adminPlanSummary">{plan.summary}</p>
        <p className="adminDetail">
          <code>{plan.planId}</code> · <code>{plan.planSha.slice(0, 23)}…</code>
        </p>

        {!outcome && (
          <>
            <section aria-label={t("admin.plan.effects")}>
              <h4>{t("admin.plan.effects")}</h4>
              <dl className="adminFacts">
                <div>
                  <dt>{t("admin.plan.effects.reads")}</dt>
                  <dd>
                    {plan.effects.filesRead.length > 0
                      ? plan.effects.filesRead.map((path) => <code key={path}>{path}</code>)
                      : t("admin.plan.effects.none")}
                  </dd>
                </div>
                <div>
                  <dt>{t("admin.plan.effects.writes")}</dt>
                  <dd>
                    {plan.effects.filesWrite.length > 0
                      ? plan.effects.filesWrite.map((path) => <code key={path}>{path}</code>)
                      : t("admin.plan.effects.none")}
                  </dd>
                </div>
                <div>
                  <dt>{t("admin.plan.effects.external")}</dt>
                  <dd>
                    {plan.effects.externalCalls.length > 0
                      ? plan.effects.externalCalls.map((call) => <code key={call}>{call}</code>)
                      : t("admin.plan.effects.none")}
                  </dd>
                </div>
                <div>
                  <dt>{t("admin.plan.effects.snapshot")}</dt>
                  <dd>
                    {plan.effects.snapshotInvalidated
                      ? t("admin.plan.effects.snapshotInvalidated")
                      : t("admin.plan.effects.snapshotKept")}
                  </dd>
                </div>
                <div>
                  <dt>{t("admin.plan.undo")}</dt>
                  <dd>
                    {plan.undo.available
                      ? t("admin.plan.undo.available", { kind: plan.undo.kind || "" })
                      : t("admin.plan.undo.unavailable")}
                  </dd>
                </div>
              </dl>
            </section>

            {plan.diff && (
              <section aria-label={t("admin.plan.diff")}>
                <h4>{t("admin.plan.diff")}</h4>
                <pre className="adminPlanDiff">{plan.diff}</pre>
              </section>
            )}

            <section aria-label={t("admin.plan.preconditions")}>
              <h4>{t("admin.plan.preconditions")}</h4>
              <ul className="adminPlanPreconditions">
                {plan.preconditions.map((entry) => (
                  <li key={entry.id}>
                    <code>{entry.id}</code>
                    <small>{shortExpected(entry.expected)}</small>
                  </li>
                ))}
              </ul>
            </section>

            {error && (
              <p className="adminUnlockError" role="alert">
                {t(`admin.plan.error.${error.code}`)}
                {error.failedPreconditions.length > 0 && (
                  <>
                    {" "}
                    (<code>{error.failedPreconditions.join(", ")}</code>)
                  </>
                )}
                {REPLAN_ERRORS.has(error.code) && ` ${t("admin.plan.replanHint")}`}
              </p>
            )}

            {confirmation.kind === "typed" && confirmation.text && (
              <div className="adminPlanConfirm">
                <label htmlFor="adminPlanConfirmation">
                  {t("admin.plan.typeToConfirm", { text: confirmation.text })}
                </label>
                <input
                  id="adminPlanConfirmation"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  value={typed}
                  placeholder={confirmation.text}
                  onChange={(event) => setTyped(event.target.value)}
                />
              </div>
            )}

            <div className="dockActions">
              <button
                className="primaryButton"
                type="button"
                disabled={executing || !typedSatisfied}
                onClick={() => void execute()}
              >
                <Play size={14} aria-hidden />
                <span>
                  {executing
                    ? t("admin.plan.executing")
                    : confirmation.kind === "simple" && confirmation.text
                      ? confirmation.text
                      : t("admin.plan.execute")}
                </span>
              </button>
              <button className="secondaryButton" type="button" onClick={onClose}>
                {t("admin.plan.cancel")}
              </button>
            </div>
          </>
        )}

        {outcome && (
          <section aria-label={t("admin.plan.result")}>
            <h4>{t("admin.plan.result")}</h4>
            <p role="status">
              {outcome.status === "success"
                ? outcome.dryRun
                  ? t("admin.plan.result.dryRunSuccess")
                  : t("admin.plan.result.success")
                : t("admin.plan.result.failed")}
            </p>
            {outcome.affectedPaths.length > 0 && (
              <p>
                {t("admin.plan.result.affected")}{" "}
                {outcome.affectedPaths.map((path) => (
                  <code key={path}>{path}</code>
                ))}
              </p>
            )}
            {outcome.snapshotInvalidated && <p>{t("admin.plan.result.snapshotInvalidated")}</p>}
            <p>
              {outcome.undo.available
                ? t("admin.plan.undo.available", { kind: outcome.undo.kind || "" })
                : t("admin.plan.undo.unavailable")}
            </p>
            {/* Output was redacted server-side before it ever reached here. */}
            <pre className="adminPlanOutput">{JSON.stringify(outcome.output, null, 2)}</pre>
            <div className="dockActions">
              <button className="secondaryButton" type="button" onClick={onClose}>
                {t("surface.close")}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
