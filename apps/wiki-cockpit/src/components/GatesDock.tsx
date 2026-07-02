// GatesDock (?dock=gates): Saúde dissolves into the world. Health is the
// weather (the radar IS freshness) plus these five honesty gates, each shown
// with its REAL last-run status (persisted receipts) and a Run button — so the
// verdict can finally turn green in-session, and "not run" is honest, never an
// eternal amber. /health redirects here; the radar's own filter chips carry the
// freshness story.

import { useState } from "react";
import { Check, Play, RefreshCw, X } from "lucide-react";
import { t } from "../data/i18n";
import { runGate } from "../data/snapshot";
import type { GateRecord, SnapshotBundle } from "../types";

const GATE_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

const GATE_LABEL: Record<string, string> = {
  wiki_audit: "Auditoria (honestidade)",
  methodology_coverage: "Cobertura de método",
  operation_compile: "Compilação operacional",
  input_stage: "Estágio de entrada",
  pytest: "Testes"
};

export function GatesDock({
  bundle,
  onNotice,
  onRefetch,
  onClose
}: {
  bundle: SnapshotBundle;
  onNotice: (text: string) => void;
  onRefetch: () => void;
  onClose: () => void;
}) {
  const gates: GateRecord[] = bundle.gates?.gates ?? [];
  const overall = bundle.gates?.status ?? "not_run";
  const [running, setRunning] = useState<string | null>(null);

  const run = async (gateId: string) => {
    setRunning(gateId);
    try {
      await runGate(gateId);
      onNotice(GATE_LABEL[gateId] ?? gateId);
      onRefetch();
    } finally {
      setRunning(null);
    }
  };
  const runAll = async () => {
    setRunning("*");
    try {
      for (const gate of gates) {
        await runGate(gate.id);
      }
      onRefetch();
    } finally {
      setRunning(null);
    }
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="gatesDock worldDock" role="dialog" aria-label={t("gate.gates.label")}>
        <header className="dockHeader">
          <strong>{t("gate.gates.label")}</strong>
          <span className={`pill pill-${GATE_TONE[overall] ?? "muted"}`}>{t(`gate.gate.${overall}`)}</span>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("gate.intro")}</p>

        <ul className="gatesList">
          {gates.map((gate) => {
            const status = (gate as GateRecord & { status: string }).status;
            const finished = (gate as GateRecord & { finished_at?: string }).finished_at;
            const busy = running === gate.id || running === "*";
            return (
              <li key={gate.id} className={`gateRow gateRow-${GATE_TONE[status] ?? "muted"}`}>
                <div className="gateRowHead">
                  {status === "pass" ? <Check size={14} className="rungOk" aria-hidden /> : <span className={`rungDot ${status === "fail" ? "rungBlocked" : "rungPending"}`} aria-hidden />}
                  <span>{GATE_LABEL[gate.id] ?? gate.id}</span>
                  <span className={`pill pill-${GATE_TONE[status] ?? "muted"}`}>{t(`gate.gate.${status}`)}</span>
                </div>
                {finished && <small className="gateFinished">{finished.replace("T", " ").slice(0, 16)}</small>}
                <button className="textButton" onClick={() => run(gate.id)} disabled={busy} type="button">
                  <Play size={12} />
                  <span>{busy ? t("gate.running") : t("gate.runGates")}</span>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="dockActions">
          <button className="secondaryButton" onClick={runAll} disabled={running !== null} type="button">
            <RefreshCw size={14} />
            <span>{running === "*" ? t("gate.running") : t("gate.runGates")}</span>
          </button>
        </div>
      </aside>
    </>
  );
}
