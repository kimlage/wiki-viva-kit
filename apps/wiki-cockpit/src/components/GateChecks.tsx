// GateChecks: the shared per-check list used by the Gate dock (?dock=approve)
// and the Checks dock (?dock=gates). Each gate shows its REAL persisted status,
// a Run button, and — because receipts persist status only — the redacted
// stdout/stderr captured from runs made in THIS session. A failing check offers
// "Fix with Codex": a verify brief carrying the failure evidence, so diagnosis
// flows straight into delegated work instead of a dead end.

import { useState } from "react";
import { Check, Loader2, Play, Sparkles } from "lucide-react";
import { t } from "../data/i18n";
import { gateFixSpec, trimGateOutput } from "../data/approval";
import { ExpandablePre } from "./ExpandablePre";
import type { BriefSpec, GateRecord, GateRunResult } from "../types";
import type { OperatorPort } from "../application/ports";

const GATE_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

// The first meaningful line of a failure — the human-readable WHY, capped so it
// stays one line inline. Skips a leading "…" (the trimmed-tail marker) and
// blank lines; the full log still lives one click away.
function failureReason(output: string): string {
  const line = output
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l && l !== "…" && l !== "--- stderr ---");
  if (!line) return "";
  return line.length > 200 ? `${line.slice(0, 200)}…` : line;
}

// Human names for the honesty gates (EN+PT via i18n; id is the fallback
// for gates this build does not know yet).
export function gateName(id: string): string {
  const key = `gate.name.${id}`;
  const label = t(key);
  return label === key ? id : label;
}

export function GateChecks({
  gates,
  busy,
  demo,
  runGate,
  onComposeBrief,
  onNotice,
  onRefetch
}: {
  gates: GateRecord[];
  busy?: boolean;
  demo?: boolean;
  runGate: OperatorPort["runGate"];
  onComposeBrief?: (spec: BriefSpec) => void;
  onNotice: (text: string) => void;
  onRefetch: () => void;
}) {
  const [running, setRunning] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<Record<string, GateRunResult>>({});
  const [openOutput, setOpenOutput] = useState<string | null>(null);

  // A run result may only PAINT a row when the gate genuinely executed
  // (returncode present). A 400 (unknown gate / version skew) or a transport
  // failure must toast, never fabricate a red "fail" over an honest receipt.
  const runOne = async (gateId: string) => {
    try {
      const result = await runGate(gateId);
      if (result.ok || typeof result.returncode === "number") {
        setLastRun((prev) => ({ ...prev, [gateId]: result }));
      } else {
        onNotice(t("gate.runFailed", { gate: gateName(gateId), error: result.error || "?" }));
      }
    } catch (error) {
      onNotice(t("gate.runFailed", { gate: gateName(gateId), error: error instanceof Error ? error.message : "offline" }));
    }
  };
  const run = async (gateId: string) => {
    if (demo) {
      onNotice(t("demo.actionsOff"));
      return;
    }
    setRunning(gateId);
    try {
      await runOne(gateId);
      onRefetch();
    } finally {
      setRunning(null);
    }
  };
  const runAll = async () => {
    if (demo) {
      onNotice(t("demo.actionsOff"));
      return;
    }
    setRunning("*");
    try {
      // One failing/skewed gate must not silently strand the rest.
      for (const gate of gates) {
        await runOne(gate.id);
      }
      onRefetch();
    } finally {
      setRunning(null);
    }
  };

  return (
    <>
      <ul className="gatesList">
        {gates.map((gate) => {
          const runResult = lastRun[gate.id];
          // Session run result is fresher than the snapshot receipt (the
          // snapshot lags behind by its cache window).
          const status = runResult ? (runResult.ok ? "pass" : "fail") : gate.status;
          const finished = runResult?.finished_at ?? gate.finished_at ?? null;
          const output = runResult ? trimGateOutput(runResult.stdout ?? "", runResult.stderr ?? "") : "";
          const rowBusy = running === gate.id || running === "*";
          const failing = status === "fail";
          // The one-line WHY of a failure, shown inline so the operator sees
          // what broke without opening anything ("Ver saída" reveals the full
          // log). Loading/running rows show a spinner and mute stale verdicts.
          const reason = failing ? failureReason(output) : "";
          const pillTone = rowBusy ? "muted" : GATE_TONE[status] ?? "muted";
          const pillLabel = rowBusy ? t("gate.running") : t(`gate.gate.${status}`);
          return (
            <li key={gate.id} className={`gateRow gateRow-${rowBusy ? "muted" : GATE_TONE[status] ?? "muted"}`}>
              <div className="gateRowHead">
                <span className="gateStatusIcon" aria-hidden>
                  {rowBusy ? (
                    <Loader2 size={13} className="gateSpin" />
                  ) : status === "pass" ? (
                    <Check size={14} className="rungOk" />
                  ) : (
                    <span className={`rungDot ${failing ? "rungBlocked" : "rungPending"}`} />
                  )}
                </span>
                <span className="gateRowName">{gateName(gate.id)}</span>
                <span className={`pill pill-${pillTone}`}>{pillLabel}</span>
                <button
                  className="textButton gateRunBtn"
                  onClick={() => run(gate.id)}
                  disabled={Boolean(demo) || rowBusy || Boolean(busy)}
                  aria-label={demo ? `${t("gate.run")} ${gateName(gate.id)} — ${t("demo.readOnlyControl")}` : undefined}
                  title={demo ? t("demo.readOnlyControl") : undefined}
                  type="button"
                >
                  <Play size={12} />
                  <span>{t("gate.run")}</span>
                </button>
              </div>
              <code className="gateRowCmd">{gate.argv.join(" ")}</code>
              {finished && <span className="gateRowTime">{finished.replace("T", " ").slice(0, 16)}</span>}
              {failing && reason && <p className="gateRowReason">{reason}</p>}
              {(output || (failing && onComposeBrief)) && (
                <div className="gateRowActions">
                  {output && (
                    <button
                      className="textButton"
                      onClick={() => setOpenOutput(openOutput === gate.id ? null : gate.id)}
                      type="button"
                    >
                      {openOutput === gate.id ? t("gate.output.hide") : t("gate.output.show")}
                    </button>
                  )}
                  {failing && onComposeBrief && (
                    <button
                      className="textButton gateFixButton"
                      onClick={() => onComposeBrief(gateFixSpec(gate, output || undefined))}
                      disabled={Boolean(demo)}
                      aria-label={demo ? `${t("gate.fix")} — ${t("demo.readOnlyControl")}` : undefined}
                      title={demo ? t("demo.readOnlyControl") : undefined}
                      type="button"
                    >
                      <Sparkles size={12} />
                      <span>{t("gate.fix")}</span>
                    </button>
                  )}
                </div>
              )}
              {openOutput === gate.id && output && (
                <ExpandablePre text={output} title={gateName(gate.id)} className="gateOutput" />
              )}
              {failing && !output && !rowBusy && <small className="gateRowHint">{t("gate.output.pending")}</small>}
            </li>
          );
        })}
      </ul>
      <div className="gateChecksActions">
        <button
          className="secondaryButton"
          onClick={runAll}
          disabled={Boolean(demo) || running !== null || Boolean(busy)}
          aria-label={demo ? `${t("gate.runGates")} — ${t("demo.readOnlyControl")}` : undefined}
          title={demo ? t("demo.readOnlyControl") : undefined}
          type="button"
        >
          <Play size={14} />
          <span>{running === "*" ? t("gate.running") : t("gate.runGates")}</span>
        </button>
      </div>
    </>
  );
}
