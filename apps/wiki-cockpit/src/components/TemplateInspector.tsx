// TemplateInspector: makes a page's TYPE — its mold — visible. Opened from the
// reader's type chip, it shows the body template (molde), the pinned fields
// with their conformity on THIS page, how the type maps the four lenses, and —
// when a pinned field is missing — a one-click "conform to the mold" brief. The
// type stops being an invisible label and becomes a legible contract.

import { Check, FileCode, Sparkles, X } from "lucide-react";
import { t } from "../data/i18n";
import { conforms, type PinnedFieldStatus } from "../data/templates";
import type { BriefSpec, PageRecord, TemplateSpec } from "../types";

const FACET_LABEL_KEY: Record<string, string> = {
  intencao: "facet.intencao",
  pratica: "facet.pratica",
  relacoes: "facet.relacoes",
  sistemas: "facet.sistemas"
};

export function TemplateInspector({
  spec,
  page,
  status,
  facetsOrder,
  onComposeBrief,
  onClose
}: {
  spec: TemplateSpec;
  page: PageRecord;
  status: PinnedFieldStatus[];
  facetsOrder: string[];
  onComposeBrief?: (spec: BriefSpec) => void;
  onClose: () => void;
}) {
  const missing = status.filter((s) => !s.present).map((s) => s.field);
  const isConform = conforms(status);
  const facetEntries = facetsOrder.filter((facet) => (spec.facets[facet] ?? []).length > 0);

  const fixToMold = () => {
    if (!onComposeBrief) return;
    onComposeBrief({
      mission_kind: "verify",
      theme: `conform-${page.id}`,
      grounding: { page_ids: [page.id], attach_context_package: true },
      intent:
        `Conform the page \`${page.path}\` to its \`${spec.page_type}\` template.\n\n` +
        `Missing pinned fields: ${missing.join(", ")}.\n` +
        `Fill them from the page's real content and evidence — never invent values. ` +
        `The body skeleton lives at ${spec.body_template || "(none)"}.`
    });
  };

  return (
    <div className="templateInspector" role="dialog" aria-label={t("template.inspector.title")}>
      <header>
        <FileCode size={14} aria-hidden />
        <strong>{t("template.inspector.title")}</strong>
        <span className={`pill pill-${isConform ? "good" : "warn"}`}>
          {isConform ? t("template.conform") : t("template.outOfMold")}
        </span>
        <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
          <X size={14} />
        </button>
      </header>

      {spec.body_template && (
        <p className="templateMold">
          {t("template.mold")}: <code>{spec.body_template}</code>
        </p>
      )}

      {status.length > 0 && (
        <div className="templatePinned">
          <span className="templateLabel">{t("template.pinned")}</span>
          <ul>
            {status.map((s) => (
              <li key={s.field} className={s.present ? "pinnedOk" : "pinnedMissing"}>
                {s.present ? <Check size={12} /> : <span className="pinnedDot" aria-hidden />}
                <code>{s.field}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {facetEntries.length > 0 && (
        <div className="templateFacets">
          <span className="templateLabel">{t("template.lenses")}</span>
          <ul>
            {facetEntries.map((facet) => (
              <li key={facet}>
                <strong>{t(FACET_LABEL_KEY[facet] ?? facet)}</strong>
                <small>{(spec.facets[facet] ?? []).join(", ")}</small>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!isConform && onComposeBrief && (
        <button className="textButton templateFixButton" onClick={fixToMold} type="button">
          <Sparkles size={12} />
          <span>{t("template.fix")}</span>
        </button>
      )}
    </div>
  );
}
