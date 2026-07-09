// CreateDock (?dock=create): the DECLARED 2D FALLBACK of the create flow — a
// bottom sheet used only when the canvas cannot host the spatial SeedFlow
// (reduced motion / no WebGL / visual-test mode; see scene/spatial.tsx for the
// primary surface). Same curated palette (data/creation.ts), same brief:
// creating never writes — it hands a create brief to Codex (scaffold → fill →
// draft PR); in the genesis tutorial the same act rebuilds the world instantly.

import { useMemo, useState } from "react";
import { ChevronLeft, Search, Sprout, X } from "lucide-react";
import { DockTelemetryRail, type DockTelemetryItem } from "./DockTelemetryRail";
import { t } from "../data/i18n";
import { contextLabel, pageTypeLabel } from "../data/presentation";
import { AUTO_FIELDS, contextsOf, createBriefSpec, curatedPalette, registryHomeOverrides } from "../data/creation";
import { composeInstruments } from "../data/surfaces";
import { typeDescription, typeIcon, typeNameExample, typeNamePrompt } from "../data/typeCatalog";
import { homeQuadrant, SCENE_FACETS, type SceneFacet } from "../scene/facets";
import type { BriefSpec, SnapshotBundle, TemplateSpec } from "../types";

// The four quadrants plus a "core" bucket for types with no AQAL home.
type Bucket = SceneFacet | "core";
const BUCKET_ORDER: Bucket[] = [...SCENE_FACETS, "core"];

export function CreateDock({
  bundle,
  initialType,
  initialQuadrant,
  genesis = false,
  onComposeBrief,
  onHighlightQuadrant,
  onClose
}: {
  bundle: SnapshotBundle;
  initialType?: string;
  initialQuadrant?: string;
  // Tutorial mode: creating rebuilds the world instantly (the honest footnote
  // changes — no Codex/PR language when nothing of the sort will happen).
  genesis?: boolean;
  onComposeBrief: (spec: BriefSpec) => void;
  // Lets the WORLD react to the choice: the selected type's home region is
  // scoped/lit behind the sheet (quadrant-aware perspectives only).
  onHighlightQuadrant?: (facet: string | null) => void;
  onClose: () => void;
}) {
  // Narrow screens get a TWO-STEP flow: pick a type → the sheet flips to the
  // mold with a back button (side-by-side needs ~760px).
  const [mobileForm, setMobileForm] = useState(false);
  const types = bundle.templates?.types ?? {};
  const overrides = useMemo(() => registryHomeOverrides(types), [types]);
  const contexts = contextsOf(bundle);
  // The palette follows the STACK: quadrant grouping is an arrangement the
  // quadrants block CONTRIBUTES; the scope's catalog floats its types first.
  const instruments = useMemo(() => composeInstruments(bundle), [bundle]);
  const byQuadrant = instruments.createArrangement === "by_quadrant";
  const catalog = instruments.createCatalog;

  const [filter, setFilter] = useState("");
  // R2 — the curated palette: only CREATABLE types exist here (generated/
  // system/rite-owned types never appear), the scope's catalog is the small
  // first level, everything else waits behind "more types…".
  const palette = useMemo(() => curatedPalette(types, catalog), [types, catalog]);
  const [expanded, setExpanded] = useState(palette.primary.length === 0);
  const orderedTypes = useMemo(() => {
    const names = expanded ? [...palette.primary, ...palette.rest] : palette.primary;
    const needle = filter.trim().toLowerCase();
    if (!needle) return names;
    return names.filter(
      (pt) =>
        pageTypeLabel(pt).toLowerCase().includes(needle) ||
        typeDescription(pt).toLowerCase().includes(needle) ||
        pt.includes(needle)
    );
  }, [palette, expanded, filter]);

  const buckets = useMemo(() => {
    const out: Record<Bucket, string[]> = { intencao: [], pratica: [], relacoes: [], sistemas: [], core: [] };
    for (const pt of orderedTypes) {
      const home = byQuadrant ? homeQuadrant(pt, overrides) ?? "core" : "core";
      out[home].push(pt);
    }
    return out;
  }, [orderedTypes, overrides, byQuadrant]);

  const firstIn = (b: Bucket) => buckets[b][0];
  const creatableInitial = initialType && types[initialType] && [...palette.primary, ...palette.rest].includes(initialType);
  const defaultType =
    (creatableInitial ? initialType : "") ||
    (initialQuadrant && SCENE_FACETS.includes(initialQuadrant as SceneFacet) ? firstIn(initialQuadrant as SceneFacet) : "") ||
    orderedTypes[0] ||
    "";

  const [type, setType] = useState(defaultType);
  const [title, setTitle] = useState("");
  const [context, setContext] = useState(contexts[0] ?? "system");
  const [values, setValues] = useState<Record<string, string>>({});

  const spec: TemplateSpec | undefined = types[type];
  const home = spec ? homeQuadrant(type, overrides) : null;
  const moldGroups = useMemo(() => groupPinnedByFacet(spec), [spec]);
  const telemetry = useMemo(
    () => createTelemetry(palette, contexts, buckets, moldGroups, byQuadrant),
    [palette, contexts, buckets, moldGroups, byQuadrant]
  );
  const setField = (key: string, value: string) => setValues((v) => ({ ...v, [key]: value }));

  const pick = (pt: string) => {
    setType(pt);
    setValues({});
    setMobileForm(true);
    onHighlightQuadrant?.(homeQuadrant(pt, overrides) ?? null);
  };

  const seed = () => {
    if (!spec || !title.trim()) return;
    // Only human-groundable fields travel in the brief — the system fills the
    // automatic ones (updated_at, freshness window) at scaffold time.
    const pinned = (spec.pinned_fields ?? [])
      .filter((key) => !AUTO_FIELDS.has(key))
      .map((key) => ({
        key,
        label: fieldLabel(key),
        value: (values[key] ?? "").trim(),
        required: false
      }));
    onComposeBrief(createBriefSpec({ pageType: type, title: title.trim(), context, home, pinned }));
  };

  const renderRow = (pt: string) => (
    <button
      key={pt}
      className={pt === type ? "createTypeRow active" : "createTypeRow"}
      onClick={() => pick(pt)}
      title={typeDescription(pt)}
      type="button"
    >
      <span className="createTypeIcon" aria-hidden>{typeIcon(pt)}</span>
      <span className="createTypeText">
        <strong>{pageTypeLabel(pt)}</strong>
        <small>{typeDescription(pt)}</small>
      </span>
    </button>
  );

  return (
    <section className="createSheet" role="dialog" aria-label={t("create.title")}>
      <header className="createSheetHeader">
        <Sprout size={15} aria-hidden />
        <strong>{t("create.title")}</strong>
        <span className="createSheetIntro">{t("create.intro")}</span>
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
          <X size={16} />
        </button>
      </header>

      {Object.keys(types).length === 0 ? (
        <p className="dockIntro createEmpty">{t("create.noTypes")}</p>
      ) : (
        <div className={mobileForm ? "createSheetBody showForm" : "createSheetBody"}>
          <div className="createTelemetryWrap">
            <DockTelemetryRail label={t("create.telemetry.aria")} items={telemetry} />
          </div>
          {/* LEFT: what can be born HERE — the scope's small catalog first
              (icons + plain-language purpose); the long tail only behind an
              explicit "more types…". The filter appears with the long list. */}
          <div className="createTypeList">
            {expanded && (
              <label className="createTypeFilter">
                <Search size={13} aria-hidden />
                <input
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={t("create.searchTypes")}
                  aria-label={t("create.searchTypes")}
                />
              </label>
            )}
            {expanded && byQuadrant
              ? BUCKET_ORDER.map((bucket) =>
                  buckets[bucket].length === 0 ? null : (
                    <div className="createTypeGroup" key={bucket}>
                      <h5>{bucket === "core" ? t("quadrant.core") : t(`facet.${bucket}`)}</h5>
                      {buckets[bucket].map(renderRow)}
                    </div>
                  )
                )
              : orderedTypes.map(renderRow)}
            {!expanded && palette.rest.length > 0 && (
              <button className="createMoreTypes" onClick={() => setExpanded(true)} type="button">
                {t("seed.more", { n: palette.rest.length })}
              </button>
            )}
            {expanded && palette.primary.length > 0 && (
              <button className="createMoreTypes" onClick={() => { setExpanded(false); setFilter(""); }} type="button">
                <ChevronLeft size={12} aria-hidden /> {t("seed.less")}
              </button>
            )}
          </div>

          {/* RIGHT: the mold of the chosen type. */}
          {spec && (
            <div className="createForm">
              <div className="createFormHead">
                <button className="createBackToTypes" onClick={() => setMobileForm(false)} type="button">
                  ‹ {t("create.backToTypes")}
                </button>
                <span className="createTypeIcon big" aria-hidden>{typeIcon(type)}</span>
                <div>
                  <strong>{pageTypeLabel(type)}</strong>
                  <small>{typeDescription(type)}</small>
                </div>
                {home && (
                  <span className={`createHomePill home--${home}`}>
                    {t("create.livesIn")} {t(`facet.${home}`)}
                  </span>
                )}
              </div>

              <div className="createFormFields">
                <label className="intakeField">
                  <span>{typeNamePrompt(type)}</span>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={typeNameExample(type)}
                    autoFocus
                  />
                </label>
                {contexts.length > 0 && (
                  <label className="intakeField">
                    <span>{t("intake.context")}</span>
                    <select value={context} onChange={(e) => setContext(e.target.value)}>
                      {contexts.map((ctx) => (
                        <option key={ctx} value={ctx}>
                          {contextLabel(ctx)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {moldGroups.map(([facet, fields]) =>
                  fields.map((key) => (
                    <label className="intakeField" key={key}>
                      <span>
                        {fieldLabel(key)}
                        {facet !== "core" ? ` · ${t(`facet.${facet}`)}` : ""}
                      </span>
                      <input
                        value={values[key] ?? ""}
                        onChange={(e) => setField(key, e.target.value)}
                        placeholder={t("create.fieldPlaceholder")}
                        spellCheck={false}
                      />
                    </label>
                  ))
                )}
              </div>

              <div className="createFormFoot">
                <button className="btn btn--primary" disabled={!title.trim()} onClick={seed} type="button">
                  <Sprout size={14} />
                  <span>{t("create.seed")}</span>
                </button>
                <small className="createGateNote">{t(genesis ? "create.gateNoteGenesis" : "create.gateNote")}</small>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function createTelemetry(
  palette: { primary: string[]; rest: string[] },
  contexts: string[],
  buckets: Record<Bucket, string[]>,
  moldGroups: [Bucket, string[]][],
  byQuadrant: boolean
): DockTelemetryItem[] {
  const total = palette.primary.length + palette.rest.length;
  const bucketCount = BUCKET_ORDER.filter((bucket) => buckets[bucket].length > 0).length;
  const moldFields = moldGroups.reduce((sum, [, fields]) => sum + fields.length, 0);

  return [
    {
      key: "templates",
      label: t("create.telemetry.templates"),
      value: total,
      tone: total > 0 ? "info" : "muted",
      ratio: total > 0 ? 1 : 0,
      detail: t("create.telemetry.templatesDetail", { n: total })
    },
    {
      key: "catalog",
      label: t("create.telemetry.catalog"),
      value: `${palette.primary.length}/${total}`,
      tone: palette.primary.length > 0 ? "good" : "warn",
      ratio: total > 0 ? palette.primary.length / total : 0,
      detail: t("create.telemetry.catalogDetail", { primary: palette.primary.length, rest: palette.rest.length })
    },
    {
      key: "homes",
      label: t("create.telemetry.homes"),
      value: byQuadrant ? bucketCount : "core",
      tone: byQuadrant ? "info" : "muted",
      ratio: byQuadrant ? bucketCount / BUCKET_ORDER.length : 0,
      detail: byQuadrant ? t("create.telemetry.homesDetail", { n: bucketCount }) : t("create.telemetry.homesCore")
    },
    {
      key: "mold",
      label: t("create.telemetry.mold"),
      value: moldFields,
      tone: moldFields > 0 ? "good" : "muted",
      ratio: Math.min(moldFields / 6, 1),
      detail: t("create.telemetry.moldDetail", { fields: moldFields, contexts: contexts.length })
    }
  ];
}



// Group a template's pinned fields by the facet they belong to (spec.facets maps
// facet → field keys). Fields not claimed by any facet fall under "core".
function groupPinnedByFacet(spec: TemplateSpec | undefined): [Bucket, string[]][] {
  if (!spec) return [];
  const pinned = (spec.pinned_fields ?? []).filter((key) => !AUTO_FIELDS.has(key));
  if (pinned.length === 0) return [];
  const fieldFacet: Record<string, SceneFacet> = {};
  for (const facet of SCENE_FACETS) {
    for (const key of spec.facets?.[facet] ?? []) fieldFacet[key] = facet;
  }
  const groups = new Map<Bucket, string[]>();
  for (const key of pinned) {
    const bucket: Bucket = fieldFacet[key] ?? "core";
    if (!groups.has(bucket)) groups.set(bucket, []);
    groups.get(bucket)!.push(key);
  }
  // Deterministic facet order, core last.
  return BUCKET_ORDER.filter((b) => groups.has(b)).map((b) => [b, groups.get(b)!]);
}

// A frontmatter key → a readable label ("source_refs" → "Source refs").
function fieldLabel(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
