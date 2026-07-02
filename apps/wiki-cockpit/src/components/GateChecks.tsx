// GateChecks: the shared per-check list used by the Gate dock (?dock=approve)
// and the Checks dock (?dock=gates). Each gate shows its REAL persisted status,
// a Run button, and — because receipts persist status only — the redacted
// stdout/stderr captured from runs made in THIS session. A failing check offers
// "Fix with Codex": a verify brief carrying the failure evidence, so diagnosis
// flows straight into delegated work instead of a dead end.

import { useState } from "react";
import { Check, Play, Sparkles } from "lucide-react";
import { t } from "../data/i18n";
import { gateFixSpec, trimGateOutput } from "../data/approval";
import { runGate } from "../data/snapshot";
import type { BriefSpec, GateRecord, GateRunResult } from "../types";

const GATE_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

// Human names for the five honesty gates (EN+PT via i18n; id is the fallback
// for gates this build does not know yet).
export function gateName(id: string): string {
  const key = `gate.name.${id}`;
  const label = t(key);
  return label === key ? id : label;
}

export function GateChecks({
  gates,
  busy,
  onComposeBrief,
  onNotice,
  onRefetch
}: {
  gates: GateRecord[];
  busy?: boolean;
  onComposeBrief?: (spec: BriefSpec) => void;
  onNotice: (text: string) => void;
  onRefetch: () => void;
}) {
  const [running, setRunning] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<Record<string, GateRunResult>>({});
  const [openOutput, setOpenOutput] = useState<string | null>(null);

  const run = async (gateId: string) => {
    setRunning(gateId);
    try {
      const result = await runGate(gateId);
      setLastRun((prev) => ({ ...prev, [gateId]: result }));
      if (!result.ok && !result.gate_id) {
        onNotice(t("gate.runFailed", { gate: gateName(gateId), error: result.error || "?" }));
      }
      onRefetch();
    } finally {
      setRunning(null);
    }
  };
  const runAll = async () => {
    setRunning("*");
    try {
      for (const gate of gates) {
        const result = await runGate(gate.id);
        setLastRun((prev) => ({ ...prev, [gate.id]: result }));
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
          return (
            <li key={gate.id} className={`gateRow gateRow-${GATE_TONE[status] ?? "muted"}`}>
              <div className="gateRowHead">
                {status === "pass" ? (
                  <Check size={14} className="rungOk" aria-hidden />
                ) : (
                  <span className={`rungDot ${failing ? "rungBlocked" : "rungPending"}`} aria-hidden />
                )}
                <span>{gateName(gate.id)}</span>
                <span className={`pill pill-${GATE_TONE[status] ?? "muted"}`}>{t(`gate.gate.${status}`)}</span>
                <button className="textButton" onClick={() => run(gate.id)} disabled={rowBusy || Boolean(busy)} type="button">
                  <Play size={12} />
                  <span>{rowBusy ? t("gate.running") : t("gate.run")}</span>
                </button>
              </div>
              <small className="gateRowMeta">
                <code>{gate.argv.join(" ")}</code>
                {finished ? ` · ${finished.replace("T", " ").slice(0, 16)}` : ""}
              </small>
              {(output || failing) && (
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
                      type="button"
                    >
                      <Sparkles size={12} />
                      <span>{t("gate.fix")}</span>
                    </button>
                  )}
                </div>
              )}
              {openOutput === gate.id && output && <pre className="gateDiff gateOutput">{output}</pre>}
              {failing && !output && <small className="gateRowHint">{t("gate.output.pending")}</small>}
            </li>
          );
        })}
      </ul>
      <div className="gateChecksActions">
        <button className="secondaryButton" onClick={runAll} disabled={running !== null || Boolean(busy)} type="button">
          <Play size={14} />
          <span>{running === "*" ? t("gate.running") : t("gate.runGates")}</span>
        </button>
      </div>
    </>
  );
}
