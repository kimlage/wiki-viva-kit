// IntakeDock (?dock=intake): Adicionar dies. Adding knowledge is an arrival, not
// a form over a fake inbox. Point at a file — even one in ~/Downloads (the exact
// dead-end of the old flow) — and it is copied into data/raw/<context>/,
// secret-scanned server-side. On success the operator can draft the ingestion
// with Codex. The already-added catalog is NOT an inbox; it lives in the
// Districts view (raw data). Everything t()'d EN+PT.

import { useState } from "react";
import { FilePlus, Sparkles, X } from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel } from "../data/presentation";
import { contextsOf } from "../data/creation";
import { intakeCopy } from "../data/snapshot";
import type { BriefSpec, SnapshotBundle } from "../types";

export function IntakeDock({
  bundle,
  initialSrc,
  onComposeBrief,
  onOpenCreate,
  onNotice,
  onClose
}: {
  bundle: SnapshotBundle;
  initialSrc?: string;
  onComposeBrief?: (spec: BriefSpec) => void;
  onOpenCreate?: () => void;
  onNotice: (text: string) => void;
  onClose: () => void;
}) {
  const contexts = contextsOf(bundle);
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
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("intake.intro")}</p>

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
