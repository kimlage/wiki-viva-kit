// CreateDock (?dock=create): "Semear no quadrante" — the type-driven replacement
// for the old dropdown. The page TYPE is the seed: it is chosen from a palette
// grouped by the four AQAL quadrants (each type lands in its home quadrant), and
// the type drives the mold — the pinned fields the template declares, shown as
// a fillable form grouped by facet. Composing never writes a file: it hands a
// `create` brief to Codex (scaffold → fill → draft PR), so creation stays gated.
// Everything t()'d EN+PT.

import { useMemo, useState } from "react";
import { Sprout, X } from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel, pageTypeLabel } from "../data/presentation";
import { homeQuadrant, SCENE_FACETS, type SceneFacet } from "../scene/facets";
import type { BriefSpec, SnapshotBundle, TemplateSpec } from "../types";

// The four quadrants plus a "core" bucket for types with no AQAL home.
type Bucket = SceneFacet | "core";
const BUCKET_ORDER: Bucket[] = [...SCENE_FACETS, "core"];

export function CreateDock({
  bundle,
  initialType,
  initialQuadrant,
  onComposeBrief,
  onClose
}: {
  bundle: SnapshotBundle;
  initialType?: string;
  initialQuadrant?: string;
  onComposeBrief: (spec: BriefSpec) => void;
  onClose: () => void;
}) {
  const types = bundle.templates?.types ?? {};
  const overrides = useMemo(() => registryHomeOverrides(types), [types]);
  const contexts = Object.keys(bundle.freshness?.by_context ?? {}).sort();

  // Group the type palette by home quadrant (per-type registry override wins).
  const buckets = useMemo(() => {
    const out: Record<Bucket, string[]> = { intencao: [], pratica: [], relacoes: [], sistemas: [], core: [] };
    for (const pt of Object.keys(types).sort()) {
      const home = homeQuadrant(pt, overrides) ?? "core";
      out[home].push(pt);
    }
    return out;
  }, [types, overrides]);

  // Default the selected type: the seed passed in the URL, else the first type
  // whose home is the active quadrant, else the first type overall.
  const firstIn = (b: Bucket) => buckets[b][0];
  const defaultType =
    (initialType && types[initialType] ? initialType : "") ||
    (initialQuadrant && SCENE_FACETS.includes(initialQuadrant as SceneFacet) ? firstIn(initialQuadrant as SceneFacet) : "") ||
    Object.keys(types).sort()[0] ||
    "";

  const [type, setType] = useState(defaultType);
  const [title, setTitle] = useState("");
  const [context, setContext] = useState(contexts[0] ?? "system");
  const [values, setValues] = useState<Record<string, string>>({});

  const spec: TemplateSpec | undefined = types[type];
  const home = spec ? homeQuadrant(type, overrides) : null;

  // Pinned fields, grouped by the facet they belong to (from spec.facets).
  const moldGroups = useMemo(() => groupPinnedByFacet(spec), [spec]);

  const setField = (key: string, value: string) => setValues((v) => ({ ...v, [key]: value }));

  const seed = () => {
    if (!spec || !title.trim()) return;
    const pinned = (spec.pinned_fields ?? []).map((key) => ({
      key,
      label: fieldLabel(key),
      value: (values[key] ?? "").trim(),
      required: false
    }));
    onComposeBrief({
      mission_kind: "create",
      theme: `new-${type}`,
      grounding: {
        attach_context_package: true,
        create: {
          page_type: type,
          title: title.trim(),
          context,
          home_facet: home,
          pinned
        }
      }
    });
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="createDock worldDock" role="dialog" aria-label={t("create.title")}>
        <header className="dockHeader">
          <strong>{t("create.title")}</strong>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("create.intro")}</p>

        {Object.keys(types).length === 0 ? (
          <p className="dockIntro createEmpty">{t("create.noTypes")}</p>
        ) : (
          <>
            {/* Type palette, grouped by home quadrant. */}
            <div className="createPalette">
              {BUCKET_ORDER.map((bucket) =>
                buckets[bucket].length === 0 ? null : (
                  <div className={`createBucket createBucket--${bucket}`} key={bucket}>
                    <h4>{bucket === "core" ? t("quadrant.core") : t(`facet.${bucket}`)}</h4>
                    <div className="createChips">
                      {buckets[bucket].map((pt) => (
                        <button
                          key={pt}
                          className={pt === type ? "createChip active" : "createChip"}
                          onClick={() => {
                            setType(pt);
                            setValues({});
                          }}
                          type="button"
                          title={pt}
                        >
                          {pageTypeLabel(pt)}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              )}
            </div>

            {spec && (
              <div className={`createMold createMold--${home ?? "core"}`}>
                <p className="createMoldHome">
                  {t("create.seedsInto")}{" "}
                  <strong>{home ? t(`facet.${home}`) : t("quadrant.core")}</strong>
                </p>

                <label className="intakeField">
                  <span>{t("create.name")}</span>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={t("create.namePlaceholder")}
                    autoFocus
                  />
                </label>
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

                {/* The mold: the template's pinned fields, grouped by facet. */}
                {moldGroups.length > 0 ? (
                  moldGroups.map(([facet, fields]) => (
                    <div className="createMoldGroup" key={facet}>
                      <h5>{facet === "core" ? t("create.moldFields") : t(`facet.${facet}`)}</h5>
                      {fields.map((key) => (
                        <label className="intakeField" key={key}>
                          <span>{fieldLabel(key)}</span>
                          <input
                            value={values[key] ?? ""}
                            onChange={(e) => setField(key, e.target.value)}
                            placeholder={t("create.fieldPlaceholder")}
                            spellCheck={false}
                          />
                        </label>
                      ))}
                    </div>
                  ))
                ) : (
                  <p className="dockIntro">{t("create.noFields")}</p>
                )}

                <div className="dockActions">
                  <button className="btn btn--primary" disabled={!title.trim()} onClick={seed} type="button">
                    <Sprout size={14} />
                    <span>{t("create.seed")}</span>
                  </button>
                </div>
                <p className="dockIntro createGateNote">{t("create.gateNote")}</p>
              </div>
            )}
          </>
        )}
      </aside>
    </>
  );
}

// Pull each type's `home_quadrant:` override out of its template spec (a wiki can
// pin a custom type into a specific quadrant). Only valid facets are kept.
function registryHomeOverrides(types: Record<string, TemplateSpec>): Record<string, SceneFacet | null> {
  const out: Record<string, SceneFacet | null> = {};
  for (const [pt, spec] of Object.entries(types)) {
    const raw = (spec as unknown as { home_quadrant?: string }).home_quadrant;
    if (raw && SCENE_FACETS.includes(raw as SceneFacet)) out[pt] = raw as SceneFacet;
  }
  return out;
}

// Group a template's pinned fields by the facet they belong to (spec.facets maps
// facet → field keys). Fields not claimed by any facet fall under "core".
function groupPinnedByFacet(spec: TemplateSpec | undefined): [Bucket, string[]][] {
  if (!spec) return [];
  const pinned = spec.pinned_fields ?? [];
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
