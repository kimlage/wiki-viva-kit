// BlocksDock (?dock=blocks): the X-ray of a focus. It answers the question the
// page_type alone can't — "what blocks are active here, where does each come
// from, and what do they make of the scope?". Two read-only modes: the STACK
// (every resolved block with its origin, the composed interface, the identity,
// and the derived quadrant/relations outputs) and the INSPECTOR (one block's
// contract). Composing a stack is F5's Setup Studio; this is the legible map.

import { useMemo, useState } from "react";
import { Boxes, ChevronLeft, X } from "lucide-react";
import { t } from "../data/i18n";
import { anchorIds, anchorRecord, blockDef, focusAnchorId, originDetail, originLabel } from "../data/blocks";
import { blockDescription, blockIcon } from "../data/typeCatalog";
import { resolvedPrimitiveDiagnostics } from "../data/visualPrimitives";
import type { BlockDefinition, QuadrantProjection, ResolvedBlock, SnapshotBundle } from "../types";

const KIND_TONE: Record<string, "good" | "warn" | "muted" | "bad"> = {
  interpretation: "good",
  interface: "warn",
  gate: "bad",
  skill: "muted"
};

export function BlocksDock({
  bundle,
  focusId,
  onSelectAnchor,
  onOpenPage,
  onAttach,
  onClose
}: {
  bundle: SnapshotBundle;
  focusId: string | null;
  onSelectAnchor: (anchorId: string) => void;
  onOpenPage: (pageId: string) => void;
  // The REAL attach action (the first Setup Studio muscle). In a live wiki it
  // composes a brief → PR; in the genesis tutorial the expected attach advances
  // the stage. Same affordance, two write paths — never a disconnected mock.
  onAttach?: (id: string, anchorId: string) => void;
  onClose: () => void;
}) {
  const anchors = useMemo(() => anchorIds(bundle), [bundle]);
  const titleById = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of bundle.pages?.pages ?? []) map.set(p.id, p.title);
    return map;
  }, [bundle]);
  // Default to the ROOT anchor (via focusAnchorId's landmark heuristic), not
  // the alphabetical first — attaching usually means "to my world", and a hub
  // that INHERITS a block must not hide it from the root's attach list.
  const activeId = focusId && anchors.includes(focusId) ? focusId : focusAnchorId(bundle, focusId ?? undefined);
  const record = anchorRecord(bundle, activeId ?? undefined);
  const [selectedBlock, setSelectedBlock] = useState<string | null>(null);
  const def = selectedBlock ? blockDef(bundle, selectedBlock) : null;

  return (
    <>
      {/* No backdrop: the world stays visible and interactive — this is an
          instrument pinned to the edge, not a modal over the galaxy. */}
      <aside className="blocksDock worldDock worldDock--glass" role="dialog" aria-label={t("blocks.title")}>
        <header className="dockHeader">
          <Boxes size={15} aria-hidden />
          <strong>{t("blocks.title")}</strong>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("blocks.intro")}</p>

        {anchors.length === 0 || !record || !activeId ? (
          <p className="dockIntro createEmpty">{t("blocks.noAnchors")}</p>
        ) : (
          <>
            <label className="blocksFocus">
              <span>{t("blocks.focus")}</span>
              <select
                value={activeId}
                onChange={(e) => {
                  setSelectedBlock(null);
                  onSelectAnchor(e.target.value);
                }}
              >
                {anchors.map((id) => (
                  <option key={id} value={id}>
                    {titleById.get(id) ?? id}
                  </option>
                ))}
              </select>
            </label>

            {def && selectedBlock ? (
              <BlockInspectorView
                blockId={selectedBlock}
                def={def}
                config={record.stack.find((b) => b.id === selectedBlock)?.config ?? {}}
                onBack={() => setSelectedBlock(null)}
              />
            ) : (
              <>
                <StackView
                  record={record}
                  titleById={titleById}
                  onInspect={setSelectedBlock}
                  onOpenPage={onOpenPage}
                />
                {onAttach && (
                  <AttachSection
                    bundle={bundle}
                    anchorId={activeId}
                    record={record}
                    onAttach={(id) => onAttach(id, activeId)}
                  />
                )}
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}

function StackView({
  record,
  titleById,
  onInspect,
  onOpenPage
}: {
  record: NonNullable<ReturnType<typeof anchorRecord>>;
  titleById: Map<string, string>;
  onInspect: (id: string) => void;
  onOpenPage: (pageId: string) => void;
}) {
  const { stack, interface: ui, identity, derived } = record;
  const visualDiagnostics = resolvedPrimitiveDiagnostics(record);
  const q = derived.quadrant_assignments ?? {};
  const projectionRows = Object.values(derived.quadrant_projections ?? {})
    .flat()
    .filter((projection) => projection.basis !== "page_semantics")
    .slice(0, 8);
  const quadrantOrder = ["q1", "q2", "q3", "q4", "q0_core"];
  const facetKey: Record<string, string> = { q1: "facet.intencao", q2: "facet.pratica", q3: "facet.relacoes", q4: "facet.sistemas", q0_core: "quadrant.core" };

  return (
    <div className="blocksBody">
      <section className="blocksSection">
        <h4>{t("blocks.stack")}</h4>
        <ul className="blockStackList">
          {stack.map((entry) => (
            <BlockRow key={entry.id} entry={entry} onInspect={onInspect} />
          ))}
        </ul>
      </section>

      <section className="blocksSection">
        <h4>{t("blocks.interface")}</h4>
        <div className="blocksGrid">
          <div><span className="blocksLabel">{t("blocks.views")}</span><strong>{ui.views.default}</strong></div>
          <div>
            <span className="blocksLabel">{t("blocks.missions")}</span>
            <strong>{ui.missions.providers.length}{ui.missions.quiet ? ` · ${t("blocks.quiet")}` : ""}</strong>
          </div>
          <div><span className="blocksLabel">{t("blocks.create")}</span><strong>{ui.create.arrangement}</strong></div>
          <div><span className="blocksLabel">{t("blocks.intake")}</span><strong>{ui.intake.forms.join(", ") || "—"}</strong></div>
          <div><span className="blocksLabel">{t("blocks.regions")}</span><strong>{ui.regions?.visual_pack ?? "—"}</strong></div>
        </div>
        {ui.create.obligations.length > 0 && (
          <p className="blocksObligations">
            {t("blocks.obligations")}: {ui.create.obligations.map((o) => o.rel).join(", ")}
          </p>
        )}
      </section>

      {visualDiagnostics.length > 0 && (
        <section className="blocksSection">
          <h4>{t("blocks.visualGrammar")}</h4>
          <div className="blocksVisualGrammar">
            {visualDiagnostics.slice(0, 6).map((entry) => (
              <span key={entry.slot} title={entry.purpose}>
                <strong>{entry.slot}</strong>
                <em>{entry.primitive}</em>
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="blocksSection">
        <h4>{t("blocks.identity")}</h4>
        <div className="blocksIdentity">
          <span className={`identityChip identity-${identity.landmark || "none"}`}>{identity.landmark || "—"}</span>
          <span className="blocksLabel">{identity.motif}</span>
          <span className="blocksLabel">{identity.horizon_text}</span>
        </div>
      </section>

      {ui.has_quadrants && (
        <section className="blocksSection">
          <h4>{t("blocks.quadrants")}</h4>
          <div className="blocksQuadrants">
            {quadrantOrder.map((quad) => {
              const ids = q[quad] ?? [];
              const empty = (derived.empty_quadrants ?? []).includes(quad);
              return (
                <div key={quad} className={`quadCell${empty ? " quadEmpty" : ""}`}>
                  <span className="quadName">{t(facetKey[quad] ?? quad)}</span>
                  <span className="quadCount">{ids.length}{empty ? ` · ${t("blocks.empty")}` : ""}</span>
                  <SubLensList sub={derived.quadrant_sub_lens?.[quad] ?? {}} />
                </div>
              );
            })}
          </div>
        </section>
      )}

      {projectionRows.length > 0 && (
        <section className="blocksSection">
          <h4>{t("blocks.projections")}</h4>
          <ul className="blocksRelations">
            {projectionRows.map((projection) => (
              <ProjectionRow
                key={`${projection.page}-${projection.quadrant}-${projection.basis}`}
                projection={projection}
                titleById={titleById}
                onOpenPage={onOpenPage}
              />
            ))}
          </ul>
        </section>
      )}

      {derived.relations && (derived.relations.due.length > 0 || derived.relations.upcoming_dates.length > 0 || derived.relations.open_commitments.length > 0) && (
        <section className="blocksSection">
          <h4>{t("blocks.relations")}</h4>
          <ul className="blocksRelations">
            {derived.relations.due.map((r) => (
              <li key={`due-${r.person}`}>
                <button className="linkish" onClick={() => onOpenPage(r.person)}>{r.title}</button>
                <span className="pill pill-warn">{t("blocks.overdue", { n: r.overdue_days })}</span>
              </li>
            ))}
            {derived.relations.upcoming_dates.map((r) => (
              <li key={`up-${r.person}`}>
                <button className="linkish" onClick={() => onOpenPage(r.person)}>{r.title}</button>
                <span className="pill pill-muted">{r.kind} · {t("blocks.inDays", { n: r.in_days })}</span>
              </li>
            ))}
            {derived.relations.open_commitments.map((r) => (
              <li key={`c-${r.person}`}>
                <button className="linkish" onClick={() => onOpenPage(r.person)}>{r.title}</button>
                <span className="pill pill-muted">{r.ref} · {t("blocks.inDays", { n: r.days_left })}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function ProjectionRow({
  projection,
  titleById,
  onOpenPage
}: {
  projection: QuadrantProjection;
  titleById: Map<string, string>;
  onOpenPage: (pageId: string) => void;
}) {
  const subject = projection.subject_center ? titleById.get(projection.subject_center) ?? projection.subject_center : "—";
  const local = projection.local_quadrant_under_subject || "—";
  return (
    <li>
      <button className="linkish" onClick={() => onOpenPage(projection.page)}>{titleById.get(projection.page) ?? projection.page}</button>
      <span className="pill pill-muted">{projection.quadrant}</span>
      <span className="blocksLabel">
        {t("blocks.projectionDetail", { subject, local, basis: projection.basis })}
      </span>
    </li>
  );
}

function SubLensList({ sub }: { sub: Record<string, string[]> }) {
  const entries = Object.entries(sub).filter(([, ids]) => ids.length > 0);
  if (entries.length === 0) return null;
  return (
    <span className="subLensList">
      {entries.map(([lens, ids]) => (
        <span key={lens} className="subLensChip">{lens} {ids.length}</span>
      ))}
    </span>
  );
}

function BlockRow({ entry, onInspect }: { entry: ResolvedBlock; onInspect: (id: string) => void }) {
  const short = entry.id.replace(/^wiki\.block\./, "").replace(/\.v\d+$/, "");
  const detail = originDetail(entry.origin);
  const description = blockDescription(entry.id);
  return (
    <li className="blockRow">
      <button
        className="blockRowMain"
        onClick={() => onInspect(entry.id)}
        title={description || short}
        type="button"
      >
        <span className={`blockIcon tone-${KIND_TONE[entry.kind] ?? "muted"}`} aria-hidden>{blockIcon(entry.id)}</span>
        <span className="blockRowText">
          <strong>{short.replace(/_/g, " ")}</strong>
          {description && <small>{description}</small>}
        </span>
      </button>
      <span className="blockOrigin" title={detail}>{t(`blocks.origin.${originLabel(entry.origin)}`)}</span>
    </li>
  );
}

function BlockInspectorView({
  blockId,
  def,
  config,
  onBack
}: {
  blockId: string;
  def: BlockDefinition;
  config: Record<string, unknown>;
  onBack: () => void;
}) {
  const profile = def.scene_profile ?? {};
  return (
    <div className="blocksBody">
      <button className="blocksBack" onClick={onBack} type="button">
        <ChevronLeft size={14} /> {t("blocks.back")}
      </button>
      <h3 className="blockInspectTitle">{def.title ?? blockId}</h3>
      <p className="dockIntro">{def.summary}</p>

      {def.perspectives && (
        <section className="blocksSection">
          <h4>{t("blocks.contract")}</h4>
          <ul className="blockLensMap">
            {Object.entries(def.perspectives).map(([q, pid]) => (
              <li key={q}><span className="pill pill-muted">{q}</span> {pid}</li>
            ))}
          </ul>
        </section>
      )}

      {Object.keys(config).length > 0 && (
        <section className="blocksSection">
          <h4>{t("blocks.configHere")}</h4>
          <pre className="blockConfig">{JSON.stringify(config, null, 2)}</pre>
        </section>
      )}

      <section className="blocksSection">
        <h4>{t("blocks.scene")}</h4>
        <p className="blocksLabel">layout: {String(profile.layout ?? "—")} · fallback: {profile.fallback ?? "—"} · overlays: {(profile.overlays ?? []).join(", ") || "—"}</p>
      </section>

      {def.gates && (def.gates.errors?.length || def.gates.warnings?.length) && (
        <section className="blocksSection">
          <h4>{t("blocks.gates")}</h4>
          <p className="blocksLabel">
            {(def.gates.errors ?? []).map((g) => <span key={g} className="pill pill-bad">{g}</span>)}
            {(def.gates.warnings ?? []).map((g) => <span key={g} className="pill pill-warn">{g}</span>)}
          </p>
        </section>
      )}
    </div>
  );
}

// --- Attach: what this anchor COULD carry but does not yet ------------------
// Packages first (the way setup thinks), then compatible interpretation blocks.
// Already-attached entries are silent — the section only offers what would
// actually change the world.

function AttachSection({
  bundle,
  anchorId,
  record,
  onAttach
}: {
  bundle: SnapshotBundle;
  anchorId: string;
  record: NonNullable<ReturnType<typeof anchorRecord>>;
  onAttach: (id: string) => void;
}) {
  const inStack = new Set(record.stack.map((entry) => entry.id));
  const anchorType = (bundle.pages?.pages ?? []).find((page) => page.id === anchorId)?.page_type ?? "";

  const packages = Object.entries(bundle.blocks?.packages ?? {}).filter(
    ([, pkg]) => !pkg.blocks.every((id) => inStack.has(id))
  );
  const blocks = Object.entries(bundle.blocks?.blocks ?? {}).filter(([id, def]) => {
    if (inStack.has(id)) return false;
    if (def.kind !== "interpretation") return false;
    const anchors = def.anchors ?? [];
    return anchors.length === 0 || anchors.includes(anchorType);
  });
  if (packages.length === 0 && blocks.length === 0) return null;

  return (
    <section className="blocksSection blocksAttach">
      <h4>{t("blocks.attach")}</h4>
      <p className="blocksLabel">{t("blocks.attachHint")}</p>
      <ul className="blockStackList">
        {packages.map(([id, pkg]) => {
          const description = blockDescription(`package.${id}`, pkg.summary);
          return (
            <li className="blockRow attachRow" key={`pkg-${id}`} title={description}>
              <span className="blockRowMain">
                <span className="blockIcon tone-warn" aria-hidden>{blockIcon(id)}</span>
                <span className="blockRowText">
                  <strong>{pkg.title}</strong>
                  <small>{description}</small>
                </span>
              </span>
              <button className="attachButton" onClick={() => onAttach(id)} title={description} type="button">
                {t("blocks.attachCta")}
              </button>
            </li>
          );
        })}
        {blocks.map(([id, def]) => {
          const description = blockDescription(id, def.summary ?? "");
          return (
            <li className="blockRow attachRow" key={id} title={description}>
              <span className="blockRowMain">
                <span className="blockIcon tone-good" aria-hidden>{blockIcon(id)}</span>
                <span className="blockRowText">
                  <strong>{def.title ?? id}</strong>
                  <small>{description}</small>
                </span>
              </span>
              <button className="attachButton" onClick={() => onAttach(id)} title={description} type="button">
                {t("blocks.attachCta")}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
