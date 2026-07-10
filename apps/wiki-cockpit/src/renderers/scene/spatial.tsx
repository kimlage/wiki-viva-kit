// Spatial UI primitives — the interface that lives IN the world, not over it.
// Four surfaces share the same anchored-plate language the quest markers
// established (one element expands in place; nothing floats detached):
//
//   FoundingRite  — an empty world's ONLY interface: 3+1 cards in the void,
//                   a ghost root, ONE question. No lists, no sheets.
//   SeedFlow      — creating a page: pick from the scope's curated catalog
//                   (cards over the world), a ghost appears at the type's home
//                   region, one name question anchored to it.
//   WorldPlate    — first reading level: click a node, get its summary plate
//                   at the node. The full reader is the second, chosen step.
//   GuideBeacon   — the tutorial's voice, anchored to the SUBJECT of the step,
//                   present before/during/after the action. Never generic.
//
// Laws: the world stays orbitable behind every surface (plates never capture
// the canvas pointer), Esc/Back always exist, one work surface at a time.

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MutableRefObject, ReactNode, RefObject } from "react";
import * as THREE from "three";
import { ChevronLeft, ExternalLink, ListChecks, Route, Sparkles, Sprout, X } from "lucide-react";
import { t } from "../../data/i18n";
import { contextLabel, contextStyle, pageTypeLabel, trustColor } from "../../data/presentation";
import { createBriefSpec, curatedPalette, registryHomeOverrides } from "../../data/creation";
import { typeDescription, typeIcon, typeNameExample, typeNamePrompt } from "../../data/typeCatalog";
import { homeQuadrant, QUADRANT_CENTER_ANGLE, SCENE_FACETS } from "../../scene/facets";
import type { SceneFacet } from "../../scene/facets";
import type { LayoutNode } from "../../scene/layout";
import type { BriefSpec, TemplateSpec } from "../../types";

// One Html wrapper for every spatial surface: same wrapperClass the canvas
// pointer-missed handler excludes, high z so plates ride over labels.
function safeScreenCenter(
  portal: RefObject<HTMLElement | null> | undefined,
  size: { width: number; height: number }
): [number, number] {
  const host = portal?.current;
  if (!host) return [size.width / 2, size.height / 2];

  const hostRect = host.getBoundingClientRect();
  // Absolutely positioned portal children use the padding box as their
  // origin. Account for the scene shell border so WebKit does not add a
  // one-pixel downward/rightward drift to an otherwise exact safe-area fit.
  const originTop = hostRect.top + host.clientTop;
  const topStrip = host.querySelector<HTMLElement>(".worldTopStrip")?.getBoundingClientRect();
  const commandBar = host.querySelector<HTMLElement>(".worldCommandBar")?.getBoundingClientRect();
  const safeTop = Math.max(8, (topStrip?.bottom ?? originTop) - originTop + 8);
  const safeBottom = Math.min(
    host.clientHeight - 8,
    (commandBar?.top ?? hostRect.bottom) - originTop - 8
  );

  return [host.clientWidth / 2, (safeTop + Math.max(safeTop, safeBottom)) / 2];
}

function Plate({
  position,
  className,
  distanceFactor = 7,
  portal,
  screenSized = false,
  z = 70,
  children
}: {
  position: [number, number, number];
  className: string;
  distanceFactor?: number;
  portal?: RefObject<HTMLElement | null>;
  screenSized?: boolean;
  z?: number;
  children: ReactNode;
}) {
  return (
    <Html
      position={position}
      center
      distanceFactor={screenSized ? undefined : distanceFactor}
      // Drei's declaration predates nullable React refs; the runtime accepts
      // the same ref object while it is null before mount.
      portal={portal as MutableRefObject<HTMLElement> | undefined}
      calculatePosition={
        screenSized
          ? (_object, _camera, size) => safeScreenCenter(portal, size)
          : undefined
      }
      wrapperClass={screenSized ? "sceneHtmlLabel sceneHtmlInteractive" : "sceneHtmlLabel"}
      className={className}
      zIndexRange={[z, 0]}
    >
      {children}
    </Html>
  );
}

// A translucent embryo: the page that is ABOUT to exist, breathing at the spot
// where it will be born. Wireframe + glow — clearly not yet real.
export function GhostNode({ position, accent }: { position: [number, number, number]; accent: string }) {
  const meshRef = useRef<THREE.Mesh | null>(null);
  useFrame((state) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const pulse = 1 + Math.sin(state.clock.elapsedTime * 2.2) * 0.08;
    mesh.scale.setScalar(0.34 * pulse);
    state.invalidate();
  });
  return (
    <group position={position}>
      <mesh ref={meshRef} scale={0.34}>
        <sphereGeometry args={[1, 18, 18]} />
        <meshBasicMaterial color={accent} wireframe transparent opacity={0.55} toneMapped={false} />
      </mesh>
      <mesh scale={0.16}>
        <sphereGeometry args={[1, 12, 12]} />
        <meshBasicMaterial color="#eaf6ff" transparent opacity={0.25} toneMapped={false} />
      </mesh>
    </group>
  );
}

// The single anchored question — the only form element the spatial flows use.
function QuestionPlate({
  position,
  prompt,
  placeholder,
  note,
  confirmLabel,
  backLabel,
  contexts,
  context,
  onContext,
  onConfirm,
  onBack,
  portal
}: {
  position: [number, number, number];
  prompt: string;
  placeholder: string;
  note?: string;
  confirmLabel: string;
  backLabel: string;
  contexts?: string[];
  context?: string;
  onContext?: (context: string) => void;
  onConfirm: (value: string) => void;
  onBack: () => void;
  portal?: RefObject<HTMLElement | null>;
}) {
  const [value, setValue] = useState("");
  return (
    <Plate position={position} className="questionPlate" portal={portal} z={75}>
      <div className="questionPlateBody anchoredAbove" role="dialog" aria-label={prompt}>
        <label>
          <strong>{prompt}</strong>
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && value.trim()) onConfirm(value.trim());
            }}
            placeholder={placeholder}
            autoFocus
          />
        </label>
        {contexts && contexts.length > 1 && onContext && (
          <label className="questionPlateContext">
            <span>{t("intake.context")}</span>
            <select value={context} onChange={(event) => onContext(event.target.value)}>
              {contexts.map((ctx) => (
                <option key={ctx} value={ctx}>
                  {contextLabel(ctx)}
                </option>
              ))}
            </select>
          </label>
        )}
        {note && <small className="questionPlateNote">{note}</small>}
        <div className="questionPlateActions">
          <button className="plateGhost" onClick={onBack} type="button">
            <ChevronLeft size={13} /> {backLabel}
          </button>
          <button className="plateCta" disabled={!value.trim()} onClick={() => onConfirm(value.trim())} type="button">
            <Sprout size={13} /> {confirmLabel}
          </button>
        </div>
      </div>
    </Plate>
  );
}

// ---------------------------------------------------------------------------
// FoundingRite — R1. The empty world's only interface: choose WHO this world
// is (3 cards + "something else…"), a ghost root materializes, one question.

const FOUNDING_PRIMARY = ["person", "team", "company"] as const;
const FOUNDING_OTHER = ["project", "community", "product"] as const;
const FOUNDING_CARD_X = [-2.7, 0, 2.7];

export type FoundingSpec = {
  demo: boolean;
  onFound: (rootType: string, name: string) => void;
};

export function FoundingRite({ demo, onFound }: FoundingSpec) {
  const [phase, setPhase] = useState<"choose" | "name">("choose");
  const [others, setOthers] = useState(false);
  const [rootType, setRootType] = useState<string>("");

  // Esc walks the rite backwards (name → cards → primary cards). The rite is
  // the empty world's BASE state, so there is nothing beyond that to close.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (phase === "name") setPhase("choose");
      else if (others) setOthers(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, others]);

  if (phase === "name") {
    return (
      <group>
        <GhostNode position={[0, 0, 0]} accent="#8fd0e8" />
        <QuestionPlate
          position={[0, 0.42, 0]}
          prompt={t(`genesis.founding.prompt.${rootType}`)}
          placeholder={t(`genesis.founding.eg.${rootType}`)}
          note={demo ? t("genesis.founding.note") : t("genesis.founding.noteReal")}
          confirmLabel={t("genesis.founding.confirm")}
          backLabel={t("genesis.back")}
          onConfirm={(name) => onFound(rootType, name)}
          onBack={() => setPhase("choose")}
        />
      </group>
    );
  }

  const options = others ? FOUNDING_OTHER : FOUNDING_PRIMARY;
  return (
    <group>
      {options.map((option, index) => (
        <Plate
          key={option}
          position={[FOUNDING_CARD_X[index], 0.55, 0.9]}
          className="spatialCardWrap"
          distanceFactor={7.5}
        >
          <button
            className="spatialCard"
            onClick={() => {
              setRootType(option);
              setPhase("name");
            }}
            type="button"
          >
            <strong>{t(`genesis.founding.type.${option}`)}</strong>
            <small>{t(`genesis.founding.desc.${option}`)}</small>
          </button>
        </Plate>
      ))}
      <Plate position={[0, -0.95, 1.4]} className="spatialCardWrap" distanceFactor={7.5}>
        <button className="spatialCard spatialCardMinor" onClick={() => setOthers((value) => !value)} type="button">
          {others ? (
            <>
              <ChevronLeft size={12} /> {t("genesis.back")}
            </>
          ) : (
            t("genesis.founding.other")
          )}
        </button>
      </Plate>
    </group>
  );
}

// ---------------------------------------------------------------------------
// SeedFlow — R4. Creating IN the world: curated cards (the scope's catalog),
// "more types…" behind an explicit expansion, then a ghost at the type's home
// region with one anchored question. The bottom sheet is the declared 2D
// fallback, not this.

export type SeedSpec = {
  types: Record<string, TemplateSpec>;
  catalog: string[];
  contexts: string[];
  rOuter: number;
  genesis: boolean;
  initialType?: string;
  onSeed: (spec: BriefSpec) => void;
  onCancel: () => void;
  onPreviewQuadrant?: (facet: string | null) => void;
  portal?: RefObject<HTMLElement | null>;
};

// The type's ghost position: its home quadrant's sector at mid radius, or a
// neutral center-front spot for core types.
function seedPosition(facet: SceneFacet | null, rOuter: number): [number, number, number] {
  if (!facet) return [0, 0.2, 2.0];
  const angle = QUADRANT_CENTER_ANGLE[facet];
  const radius = Math.max(rOuter * 0.55, 2.4);
  return [Math.cos(angle) * radius, 0.15, Math.sin(angle) * radius];
}


export function SeedFlow({
  types,
  catalog,
  contexts,
  rOuter,
  genesis,
  initialType,
  onSeed,
  onCancel,
  onPreviewQuadrant,
  portal
}: SeedSpec) {
  const palette = useMemo(() => curatedPalette(types, catalog), [types, catalog]);
  const overrides = useMemo(() => registryHomeOverrides(types), [types]);
  // ?src= is raw URL input: it may name a type this surface must never offer
  // (creatable:false, rite-owned root). Only palette members short-circuit the
  // picker — anything else falls back to choosing like the 2D twin does.
  const allowedInitial = useMemo(() => new Set([...palette.primary, ...palette.rest]), [palette]);
  const validInitial = initialType && allowedInitial.has(initialType) ? initialType : "";
  const [type, setType] = useState<string>(validInitial);
  const [expanded, setExpanded] = useState(palette.primary.length === 0);
  const [filter, setFilter] = useState("");
  const [context, setContext] = useState(contexts[0] ?? "system");

  const pick = (pageType: string) => {
    setType(pageType);
    onPreviewQuadrant?.(homeQuadrant(pageType, overrides));
  };

  const home = type ? homeQuadrant(type, overrides) : null;
  const ghostAt = seedPosition(home, rOuter);

  const seed = (title: string) => {
    onSeed(createBriefSpec({ pageType: type, title, context, home, pinned: [] }));
  };

  // Naming phase: the ghost breathes where the page will live; one question.
  if (type) {
    const accent = home ? "#8fd0e8" : "#9fb4c2";
    return (
      <group>
        <GhostNode position={ghostAt} accent={accent} />
        <QuestionPlate
          position={[ghostAt[0], ghostAt[1] + 0.42, ghostAt[2]]}
          prompt={typeNamePrompt(type)}
          placeholder={typeNameExample(type)}
          note={t(genesis ? "create.gateNoteGenesis" : "create.gateNote")}
          confirmLabel={t("create.seed")}
          backLabel={t("genesis.back")}
          contexts={contexts}
          context={context}
          onContext={setContext}
          onConfirm={seed}
          onBack={() => {
            onPreviewQuadrant?.(null);
            if (validInitial) onCancel();
            else setType("");
          }}
          portal={portal}
        />
      </group>
    );
  }

  // Expanded picker: one anchored plate with every creatable type, grouped by
  // quadrant home, filterable. Still anchored to the seeding spot — never a
  // screen-edge panel.
  if (expanded) {
    const needle = filter.trim().toLowerCase();
    const all = [...palette.primary, ...palette.rest].filter(
      (pageType) =>
        !needle ||
        pageTypeLabel(pageType).toLowerCase().includes(needle) ||
        typeDescription(pageType).toLowerCase().includes(needle) ||
        pageType.includes(needle)
    );
    const buckets = new Map<SceneFacet | "core", string[]>();
    for (const pageType of all) {
      const bucket = homeQuadrant(pageType, overrides) ?? "core";
      buckets.set(bucket, [...(buckets.get(bucket) ?? []), pageType]);
    }
    const order: (SceneFacet | "core")[] = [...SCENE_FACETS, "core"];
    return (
      <Plate position={[0, 0.7, 1.3]} className="seedPickPlate" portal={portal} z={75}>
        <div className="seedPickBody" role="dialog" aria-label={t("seed.title")}>
          <header>
            <strong>{t("seed.title")}</strong>
            <button className="questPlateClose" onClick={onCancel} title={t("help.close")} type="button">
              ×
            </button>
          </header>
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={t("create.searchTypes")}
            aria-label={t("create.searchTypes")}
          />
          <div className="seedPickGroups">
            {order.map((bucket) => {
              const members = buckets.get(bucket) ?? [];
              if (members.length === 0) return null;
              return (
                <div key={bucket}>
                  <h5>{bucket === "core" ? t("quadrant.core") : t(`facet.${bucket}`)}</h5>
                  {members.map((pageType) => (
                    <button
                      key={pageType}
                      className="seedPickRow"
                      onClick={() => pick(pageType)}
                      title={typeDescription(pageType)}
                      type="button"
                    >
                      <span aria-hidden>{typeIcon(pageType)}</span>
                      <strong>{pageTypeLabel(pageType)}</strong>
                      <small>{typeDescription(pageType)}</small>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
          {palette.primary.length > 0 && (
            <button className="plateGhost" onClick={() => setExpanded(false)} type="button">
              <ChevronLeft size={13} /> {t("seed.less")}
            </button>
          )}
        </div>
      </Plate>
    );
  }

  // Curated picker: one plate anchored at the world's center, with individual
  // semantic cards inside it. A shared anchor keeps camera azimuth from
  // turning a screen-readable grid into a diagonal/off-screen procession.
  return (
    <group>
      <Plate position={[0, 1.95, 0]} className="seedPalettePlate" portal={portal} screenSized z={72}>
        <div className="seedPaletteBody" role="dialog" aria-label={t("seed.title")}>
          <div className="seedTitle">
            <Sprout size={13} aria-hidden />
            <strong>{t("seed.title")}</strong>
            <button className="questPlateClose" onClick={onCancel} title={t("help.close")} type="button">
              ×
            </button>
          </div>
          <div className="seedPaletteGrid">
            {palette.primary.map((pageType) => (
              <button
                key={pageType}
                className="spatialCard spatialCardType"
                onClick={() => pick(pageType)}
                onPointerEnter={() => onPreviewQuadrant?.(homeQuadrant(pageType, overrides))}
                onPointerLeave={() => onPreviewQuadrant?.(null)}
                title={typeDescription(pageType)}
                type="button"
              >
                <span className="spatialCardIcon" aria-hidden>
                  {typeIcon(pageType)}
                </span>
                <strong>{pageTypeLabel(pageType)}</strong>
                <small>{typeNamePrompt(pageType)}</small>
              </button>
            ))}
            {palette.rest.length > 0 && (
              <button className="spatialCard spatialCardMinor" onClick={() => setExpanded(true)} type="button">
                {t("seed.more", { n: palette.rest.length })}
              </button>
            )}
          </div>
        </div>
      </Plate>
    </group>
  );
}

// ---------------------------------------------------------------------------
// WorldPlate — R7. The FIRST reading level: an anchored summary at the node.
// The full reader is a chosen second step, never the price of a click.

export type WorldPlateSpec = {
  node: LayoutNode;
  onOpen: () => void;
  onTrails: () => void;
  onPacket?: () => void;
  onClose: () => void;
};

export type WorldPlatePose = {
  anchor: [number, number, number];
  subject: [number, number, number];
  className: "anchoredAbove" | "anchoredAbove worldPlateSide";
  tether: boolean;
};

export function worldPlatePose(node: LayoutNode): WorldPlatePose {
  const lift = Math.max(node.scale, 0.1) * 0.98;
  const subject: [number, number, number] = [node.position[0], node.position[1] + lift, node.position[2]];
  const pageCenter = Boolean(node.isRoot && !node.isGroup);
  if (!pageCenter) {
    return { anchor: subject, subject, className: "anchoredAbove", tether: false };
  }

  const mass = Math.max(0, node.inbound_links + node.outbound_links + node.source_ref_count);
  const side = node.position[0] <= 0 ? 1 : -1;
  const lateral = Math.min(1.55, Math.max(0.9, node.scale * 1.65 + Math.log2(mass + 1) * 0.055));
  const retreat = Math.min(0.55, Math.max(0.22, node.scale * 0.42));
  const anchor: [number, number, number] = [
    node.position[0] + side * lateral,
    node.position[1] + lift * 0.82,
    node.position[2] - retreat
  ];
  return { anchor, subject, className: "anchoredAbove worldPlateSide", tether: true };
}

function WorldPlateTether({ from, to }: { from: [number, number, number]; to: [number, number, number] }) {
  const object = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(...from),
      new THREE.Vector3(...to)
    ]);
    const material = new THREE.LineBasicMaterial({
      color: "#79c7e8",
      transparent: true,
      opacity: 0.34,
      depthWrite: false,
      toneMapped: false
    });
    const line = new THREE.Line(geometry, material);
    line.frustumCulled = false;
    line.renderOrder = 5;
    return line;
  }, [from, to]);

  useEffect(() => {
    return () => {
      object.geometry.dispose();
      (object.material as THREE.Material).dispose();
    };
  }, [object]);

  return <primitive object={object} />;
}

export function WorldPlate({ node, onOpen, onTrails, onPacket, onClose }: WorldPlateSpec) {
  const pose = worldPlatePose(node);
  const freshness =
    node.freshness_state === "unknown"
      ? t("plate.noDate")
      : node.ageDays < 1
        ? t("plate.updatedToday")
        : t("plate.updatedDays", { n: Math.round(node.ageDays) });
  return (
    <>
      {pose.tether && <WorldPlateTether from={pose.subject} to={pose.anchor} />}
      <Plate
        position={pose.anchor}
        className="worldPlateWrap"
        distanceFactor={5.4}
        z={60}
      >
      <div className={`worldPlate ${pose.className}`} role="dialog" aria-label={node.title}>
        <button className="questPlateClose" onClick={onClose} title={t("help.close")} type="button">
          ×
        </button>
        <header>
          <span className="worldPlateIcon" aria-hidden>
            {typeIcon(node.page_type)}
          </span>
          <strong>{node.title}</strong>
        </header>
        <small className="worldPlateMeta">
          {pageTypeLabel(node.page_type)} · <i style={{ background: contextStyle(node.context).accent }} />{" "}
          {contextLabel(node.context || "system")}
        </small>
        <small className="worldPlateMeta">
          <i style={{ background: trustColor(node.freshness_state === "stale" ? "stale" : node.freshness_state === "unknown" ? "unknown" : "fresh") }} />
          {t(`scene.trust.${node.freshness_state === "stale" ? "stale" : node.freshness_state === "unknown" ? "unknown" : "fresh"}`)} · {freshness}
        </small>
        <small className="worldPlateMeta">
          {t("plate.links", { in: node.inbound_links, out: node.outbound_links })}
          {node.source_ref_count > 0 ? ` · ${t("plate.sources", { n: node.source_ref_count })}` : ""}
        </small>
        <div className="worldPlateActions">
          <button className="plateCta" onClick={onOpen} title={t("scene.lock.readTitle")} type="button">
            <ExternalLink size={12} /> {t("plate.open")}
          </button>
          <button className="plateGhost" onClick={onTrails} title={t("scene.lock.trailsTitle")} type="button">
            <Route size={12} /> {t("scene.lock.trails")}
          </button>
          {onPacket && (
            <button className="plateGhost" onClick={onPacket} title={t("scene.lock.packetTitle")} type="button">
              <ListChecks size={12} /> {t("scene.lock.packet")}
            </button>
          )}
        </div>
      </div>
      </Plate>
    </>
  );
}

// ---------------------------------------------------------------------------
// GuideBeacon — R5. The tutorial's voice, anchored to the step's SUBJECT and
// present before, during and after the action. Back/Skip live on the beacon;
// while the action surface is open the beacon keeps the SPECIFIC instruction.

export type GuideSpec = {
  progress: { k: number; n: number };
  title: string;
  body: string;
  // The step's call to action; null when the world itself is the action
  // (founding cards) or on the final stage.
  cta: { label: string; onClick: () => void } | null;
  // Shown INSTEAD of the CTA while the action surface is open — the specific
  // "do this there" instruction, never a generic "use the dock".
  during: string | null;
  actionOpen: boolean;
  onBack: (() => void) | null;
  skipHref: string;
  final: { exploreHref: string; onRestart: () => void } | null;
  anchor: [number, number, number];
};

export function GuideBeacon({ progress, title, body, cta, during, actionOpen, onBack, skipHref, final, anchor }: GuideSpec) {
  return (
    <Plate position={anchor} className="guideBeaconWrap" distanceFactor={7} z={68}>
      <div className="guideBeacon anchoredAbove" role="status" aria-label={title}>
        <header>
          <span className="guideProgress">{t("genesis.progress", { k: Math.max(progress.k, 1), n: progress.n })}</span>
          <span className="guideSim">{t("genesis.sim")}</span>
        </header>
        <strong>{title}</strong>
        <small>{actionOpen && during ? during : body}</small>
        <div className="guideActions">
          {onBack && (
            <button className="plateGhost" onClick={onBack} type="button">
              <ChevronLeft size={12} /> {t("genesis.back")}
            </button>
          )}
          {!actionOpen && cta && (
            <button className="plateCta" onClick={cta.onClick} type="button">
              {cta.label}
            </button>
          )}
          {final && (
            <>
              <a className="plateCta" href={final.exploreHref}>
                <Sparkles size={12} /> {t("genesis.explore")}
              </a>
              <button className="plateGhost" onClick={final.onRestart} type="button">
                {t("genesis.restart")}
              </button>
            </>
          )}
          <a className="guideSkip" href={skipHref}>
            <X size={11} /> {t("genesis.skip")}
          </a>
        </div>
      </div>
    </Plate>
  );
}
