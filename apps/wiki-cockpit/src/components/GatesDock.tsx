// GatesDock (?dock=gates): Saúde dissolves into the world. Health is the
// weather (the radar IS freshness) plus these five honesty gates, each shown
// with its REAL last-run status (persisted receipts) and a Run button — so the
// verdict can finally turn green in-session, and "not run" is honest, never an
// eternal amber. /health redirects here; the radar's own filter chips carry the
// freshness story.

import { X } from "lucide-react";
import { t } from "../data/i18n";
import { GateChecks } from "./GateChecks";
import type { BriefSpec, GateRecord, SnapshotBundle } from "../types";

const GATE_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

export function GatesDock({
  bundle,
  demo,
  onComposeBrief,
  onNotice,
  onRefetch,
  onClose
}: {
  bundle: SnapshotBundle;
  demo?: boolean;
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
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("gate.intro")}</p>

        <GateChecks gates={gates} demo={demo} onComposeBrief={onComposeBrief} onNotice={onNotice} onRefetch={onRefetch} />
      </aside>
    </>
  );
}
