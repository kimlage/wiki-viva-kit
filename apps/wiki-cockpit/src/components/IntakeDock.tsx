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
import { intakeCopy } from "../data/snapshot";
import type { BriefSpec, SnapshotBundle } from "../types";

export function IntakeDock({
  bundle,
  initialSrc,
  onComposeBrief,
  onNotice,
  onClose
}: {
  bundle: SnapshotBundle;
  initialSrc?: string;
  onComposeBrief?: (spec: BriefSpec) => void;
  onNotice: (text: string) => void;
  onClose: () => void;
}) {
  const contexts = Object.keys(bundle.freshness?.by_context ?? {}).sort();
  const [src, setSrc] = useState(initialSrc ?? "");
  const [context, setContext] = useState(contexts[0] ?? "system");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<{ path: string; context: string } | null>(null);
  // "New typed page": pick a type from the registry, name it, and the type's
  // mold + facets flow into the brief the agent runs (create, PR-gated).
  const templateTypes = Object.keys(bundle.templates?.types ?? {}).sort();
  const [newType, setNewType] = useState(templateTypes.includes("decision") ? "decision" : templateTypes[0] ?? "");
  const [newTitle, setNewTitle] = useState("");

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

        {onComposeBrief && templateTypes.length > 0 && (
          <div className="intakeNewTyped">
            <h4>{t("intake.newTyped.title")}</h4>
            <p className="dockIntro">{t("intake.newTyped.hint")}</p>
            <label className="intakeField">
              <span>{t("intake.newTyped.type")}</span>
              <select value={newType} onChange={(event) => setNewType(event.target.value)}>
                {templateTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label className="intakeField">
              <span>{t("intake.newTyped.name")}</span>
              <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder={t("intake.newTyped.placeholder")} />
            </label>
            <button
              className="secondaryButton"
              disabled={!newTitle.trim()}
              onClick={() => {
                const spec = bundle.templates?.types?.[newType];
                onComposeBrief({
                  mission_kind: "verify",
                  theme: `new-${newType}`,
                  grounding: { attach_context_package: true },
                  intent:
                    `Create a new \`${newType}\` page titled "${newTitle.trim()}".\n\n` +
                    `Run: python3 scripts/wiki_new.py --page-type ${newType} --title "${newTitle.trim()}" --context ${context}\n` +
                    `Then fill the pinned fields (${(spec?.pinned_fields ?? []).join(", ") || "per the template"}) ` +
                    `from real content — never invent values. The mold lives at ${spec?.body_template || "(see wiki.page-types.yaml)"}.`
                });
              }}
              type="button"
            >
              <Sparkles size={14} />
              <span>{t("intake.newTyped.create")}</span>
            </button>
          </div>
        )}

        <p className="intakeCatalog dockIntro">{t("intake.catalog")}</p>
      </aside>
    </>
  );
}
