// IntakeDock (?dock=intake): Adicionar dies. Adding knowledge is an arrival, not
// a form over a fake inbox. Point at a file — even one in ~/Downloads (the exact
// dead-end of the old flow) — and it is copied into data/raw/<context>/,
// secret-scanned server-side. On success the operator can draft the ingestion
// with Codex. The already-added catalog is NOT an inbox; it lives in the
// Districts view (raw data). Everything t()'d EN+PT.

import { useState } from "react";
import { FilePlus, Sparkles, X } from "lucide-react";
import { DockTelemetryRail, type DockTelemetryItem } from "./DockTelemetryRail";
import { t } from "../data/i18n";
import { contextLabel } from "../data/presentation";
import { contextsOf } from "../data/creation";
import { composeInstruments } from "../data/surfaces";
import type { BriefSpec, SnapshotBundle } from "../types";
import type { OperatorPort } from "../application/ports";

export function IntakeDock({
  bundle,
  initialSrc,
  intakeCopy,
  onComposeBrief,
  onOpenCreate,
  onNotice,
  onClose
}: {
  bundle: SnapshotBundle;
  initialSrc?: string;
  intakeCopy: OperatorPort["intakeCopy"];
  onComposeBrief?: (spec: BriefSpec) => void;
  onOpenCreate?: () => void;
  onNotice: (text: string) => void;
  onClose: () => void;
}) {
  const contexts = contextsOf(bundle);
  const instruments = composeInstruments(bundle);
  const telemetry = intakeTelemetry(bundle, contexts, instruments.intakeForms);
  const [src, setSrc] = useState(initialSrc ?? "");
  const [context, setContext] = useState(contexts[0] ?? "system");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<{ path: string; context: string } | null>(null);

  const add = async () => {
    if (!src.trim() || busy) return;
    setBusy(true);
    setAdded(null);
    try {
      const result = await intakeCopy(src.trim(), context);
      if (result.ok && result.path) {
        setAdded({ path: result.path, context: result.context ?? context });
        onNotice(t("intake.added", { path: result.path }));
      } else {
        onNotice(result.reason === "secret_block" ? t("intake.secretBlock") : t("intake.failed", { error: result.error ?? "?" }));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="intakeDock worldDock" role="dialog" aria-label={t("intake.title")}>
        <header className="dockHeader">
          <strong>{t("intake.title")}</strong>
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("intake.intro")}</p>
        <DockTelemetryRail label={t("intake.telemetry.aria")} items={telemetry} />

        <label className="intakeField">
          <span>{t("intake.path")}</span>
          <input
            value={src}
            onChange={(event) => setSrc(event.target.value)}
            placeholder={t("intake.pathPlaceholder")}
            spellCheck={false}
          />
        </label>
        <label className="intakeField">
          <span>{t("intake.context")}</span>
          <select value={context} onChange={(event) => setContext(event.target.value)}>
            {contexts.map((ctx) => (
              <option key={ctx} value={ctx}>
                {contextLabel(ctx)}
              </option>
            ))}
          </select>
        </label>

        <div className="dockActions">
          <button className="primaryButton" onClick={add} disabled={!src.trim() || busy} type="button">
            <FilePlus size={14} />
            <span>{busy ? t("intake.adding") : t("intake.add")}</span>
          </button>
        </div>

        {added && (
          <div className="intakeResult">
            <p className="intakeAdded">{t("intake.added", { path: added.path })}</p>
            <p className="dockIntro">{t("intake.next")}</p>
            {onComposeBrief && (
              <button
                className="secondaryButton"
                onClick={() =>
                  onComposeBrief({
                    mission_kind: "ingest",
                    theme: `ingest-${added.context}`,
                    grounding: { source: { path: added.path, context: added.context }, attach_context_package: true }
                  })
                }
                type="button"
              >
                <Sparkles size={14} />
                <span>{t("intake.brief")}</span>
              </button>
            )}
          </div>
        )}

        {onComposeBrief && (
          <p className="dockIntro intakeCrossLink">
            {t("intake.createHint")}{" "}
            <a href="?dock=create" onClick={(e) => { e.preventDefault(); onOpenCreate?.(); }}>
              {t("nav.create")}
            </a>
          </p>
        )}

        <p className="intakeCatalog dockIntro">{t("intake.catalog")}</p>
      </aside>
    </>
  );
}

function intakeTelemetry(bundle: SnapshotBundle, contexts: string[], forms: string[]): DockTelemetryItem[] {
  const sourceCount = bundle.sourceEntities?.sources?.length ?? bundle.sources?.sources?.length ?? 0;
  const pendingStreams = (bundle.sourceEntities?.sources ?? []).reduce((sum, source) => sum + source.pending_streams, 0);
  return [
    {
      key: "areas",
      label: t("intake.telemetry.areas"),
      value: contexts.length,
      tone: contexts.length > 0 ? "info" : "muted",
      ratio: contexts.length > 0 ? 1 : 0,
      detail: t("intake.telemetry.areasDetail", { n: contexts.length })
    },
    {
      key: "forms",
      label: t("intake.telemetry.forms"),
      value: forms.length,
      tone: forms.length > 0 ? "good" : "warn",
      ratio: forms.length > 0 ? 1 : 0,
      detail: t("intake.telemetry.formsDetail", { n: forms.length })
    },
    {
      key: "sources",
      label: t("intake.telemetry.sources"),
      value: sourceCount,
      tone: sourceCount > 0 ? "info" : "muted",
      ratio: sourceCount > 0 ? 1 : 0,
      detail: t("intake.telemetry.sourcesDetail", { n: sourceCount })
    },
    {
      key: "pending",
      label: t("intake.telemetry.pending"),
      value: pendingStreams,
      tone: pendingStreams > 0 ? "warn" : "good",
      ratio: pendingStreams > 0 ? Math.min(pendingStreams / 8, 1) : 1,
      detail: pendingStreams > 0 ? t("intake.telemetry.pendingDetail", { n: pendingStreams }) : t("intake.telemetry.pendingClear")
    }
  ];
}
