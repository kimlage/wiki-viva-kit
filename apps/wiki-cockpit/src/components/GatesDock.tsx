// GatesDock (?dock=gates): Saúde dissolves into the world. Health is the
// weather (the radar IS freshness) plus these five honesty gates, each shown
// with its REAL last-run status (persisted receipts) and a Run button — so the
// verdict can finally turn green in-session, and "not run" is honest, never an
// eternal amber. /health redirects here; the radar's own filter chips carry the
// freshness story.

import { X } from "lucide-react";
import { t } from "../data/i18n";
import { DockTelemetryRail, type DockTelemetryItem } from "./DockTelemetryRail";
import { GateChecks } from "./GateChecks";
import type { BriefSpec, GateRecord, SnapshotBundle } from "../types";
import type { OperatorPort } from "../application/ports";

const GATE_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

function gatesTelemetry(gates: GateRecord[]): DockTelemetryItem[] {
  const total = gates.length;
  const passed = gates.filter((gate) => gate.status === "pass").length;
  const failed = gates.filter((gate) => gate.status === "fail").length;
  const partial = gates.filter((gate) => gate.status === "partial").length;
  const notRun = gates.filter((gate) => gate.status === "not_run").length;
  return [
    {
      key: "passed",
      label: t("gate.telemetry.passed"),
      value: `${passed}/${total}`,
      tone: total > 0 && passed === total ? "good" : "info",
      ratio: total > 0 ? passed / total : 0
    },
    {
      key: "failed",
      label: t("gate.telemetry.failed"),
      value: failed,
      tone: failed > 0 ? "bad" : "good",
      ratio: total > 0 ? failed / total : 0
    },
    {
      key: "partial",
      label: t("gate.telemetry.partial"),
      value: partial,
      tone: partial > 0 ? "warn" : "muted",
      ratio: total > 0 ? partial / total : 0
    },
    {
      key: "notRun",
      label: t("gate.telemetry.notRun"),
      value: notRun,
      tone: notRun > 0 ? "muted" : "good",
      ratio: total > 0 ? notRun / total : 0
    }
  ];
}

export function GatesDock({
  bundle,
  demo,
  runGate,
  onComposeBrief,
  onNotice,
  onRefetch,
  onClose
}: {
  bundle: SnapshotBundle;
  demo?: boolean;
  runGate: OperatorPort["runGate"];
  onComposeBrief?: (spec: BriefSpec) => void;
  onNotice: (text: string) => void;
  onRefetch: () => void;
  onClose: () => void;
}) {
  const gates: GateRecord[] = bundle.gates?.gates ?? [];
  const overall = bundle.gates?.status ?? "not_run";

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="gatesDock worldDock" role="dialog" aria-label={t("gate.gates.label")}>
        <header className="dockHeader">
          <strong>{t("gate.gates.label")}</strong>
          <span className={`pill pill-${GATE_TONE[overall] ?? "muted"}`}>{t(`gate.gate.${overall}`)}</span>
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("gate.intro")}</p>
        <DockTelemetryRail label={t("gate.telemetry.aria")} items={gatesTelemetry(gates)} />

        <GateChecks gates={gates} demo={demo} runGate={runGate} onComposeBrief={onComposeBrief} onNotice={onNotice} onRefetch={onRefetch} />
      </aside>
    </>
  );
}
