// Takezo, the wizard cat (plan §15) — the guide of the abrachaindabra ritual.
// A self-contained decorative easter egg: blue robe, blue wizard hat, RED
// ribbons on the hat, wise and a little mischievous. The character is pure
// costume — its colors live OUTSIDE the data legend, the ribbons' red never
// reads as risk, and seeing Takezo is never evidence of an authorized session
// (plan §3.2). v1 is fully procedural (no external assets or textures); an
// approved asset may replace it later without changing this contract.
//
// Performance contract (plan §15.4/§24.1): lazy mount only during the ritual,
// a handful of draw calls (merged geometry groups + one instanced chain),
// dispose on unmount, and zero animation when idle — useFrame invalidates
// only while a choreography phase is actually running under the scene's
// `frameloop="demand"` policy.

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import * as THREE from "three";
import { t } from "../../../data/i18n";
import {
  DEFAULT_MOTION_SPEED,
  motionDurationMs,
  motionProgress
} from "../../../world/visual/motionGrammar";
import { TAKEZO_RENDER_ORDER, TakezoPortal } from "./TakezoPortal";

// ---------------------------------------------------------------------------
// Identity (plan §15.1). Every color is deliberately absent from the trust,
// context and page-type palettes — the character may never impersonate a data
// state. The ribbon red is a deep costume crimson, far from the risk accent.
export const TAKEZO_PALETTE = {
  robe: "#3b5bc0",
  hat: "#2f4aa8",
  fur: "#b9c2d2",
  ribbon: "#b0233c",
  eyes: "#ffd97a"
} as const;

// Ritual budget (plan §24.1): the whole decorative layer — wizard plus chain
// portal — must stay at roughly eight extra draw calls.
export const TAKEZO_MAX_DRAW_CALLS = 8;

// ---------------------------------------------------------------------------
// Procedural geometry. Parts that share a material are merged into a single
// BufferGeometry so each material costs exactly one draw call.

type GeometryPart = {
  geometry: THREE.BufferGeometry;
  position?: [number, number, number];
  rotation?: [number, number, number];
  scale?: [number, number, number];
};

function mergeParts(parts: GeometryPart[]): THREE.BufferGeometry {
  const positions: number[] = [];
  const normals: number[] = [];
  const matrix = new THREE.Matrix4();
  const normalMatrix = new THREE.Matrix3();
  const vertex = new THREE.Vector3();
  const normal = new THREE.Vector3();
  for (const part of parts) {
    const source = part.geometry.toNonIndexed();
    matrix.compose(
      new THREE.Vector3(...(part.position ?? [0, 0, 0])),
      new THREE.Quaternion().setFromEuler(new THREE.Euler(...(part.rotation ?? [0, 0, 0]))),
      new THREE.Vector3(...(part.scale ?? [1, 1, 1]))
    );
    normalMatrix.getNormalMatrix(matrix);
    const positionAttribute = source.getAttribute("position");
    const normalAttribute = source.getAttribute("normal");
    for (let index = 0; index < positionAttribute.count; index += 1) {
      vertex.fromBufferAttribute(positionAttribute, index).applyMatrix4(matrix);
      positions.push(vertex.x, vertex.y, vertex.z);
      normal.fromBufferAttribute(normalAttribute, index).applyNormalMatrix(normalMatrix);
      normals.push(normal.x, normal.y, normal.z);
    }
    source.dispose();
    part.geometry.dispose();
  }
  const merged = new THREE.BufferGeometry();
  merged.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
  merged.setAttribute("normal", new THREE.BufferAttribute(new Float32Array(normals), 3));
  return merged;
}

function curveTube(points: [number, number, number][], radius: number): THREE.BufferGeometry {
  const curve = new THREE.CatmullRomCurve3(points.map((point) => new THREE.Vector3(...point)));
  return new THREE.TubeGeometry(curve, 12, radius, 5, false);
}

export type TakezoBuild = {
  group: THREE.Group;
  meshes: THREE.Mesh[];
  drawCalls: number;
  dispose: () => void;
};

/**
 * The procedural cat wizard: icosahedron head, cone ears, truncated-cone blue
 * robe, blue hat (brim + inclined cone) with red ribbon tubes, a tail curve
 * and small emissive eyes. Four material groups → four draw calls.
 */
export function buildTakezoWizard(): TakezoBuild {
  const furGeometry = mergeParts([
    // Head — a low-poly icosahedron keeps the silhouette wizardly, not toy-like.
    { geometry: new THREE.IcosahedronGeometry(0.28, 1), position: [0, 1.02, 0] },
    // Cone ears poking out under the hat brim.
    { geometry: new THREE.ConeGeometry(0.085, 0.2, 8), position: [-0.17, 1.26, 0], rotation: [0, 0, 0.32] },
    { geometry: new THREE.ConeGeometry(0.085, 0.2, 8), position: [0.17, 1.26, 0], rotation: [0, 0, -0.32] },
    // Tail — one curve out of the robe hem.
    {
      geometry: curveTube(
        [
          [0.2, 0.1, -0.28],
          [0.42, 0.22, -0.36],
          [0.5, 0.52, -0.3],
          [0.42, 0.72, -0.22]
        ],
        0.032
      )
    }
  ]);
  const robeGeometry = mergeParts([
    // Truncated-cone robe.
    { geometry: new THREE.CylinderGeometry(0.14, 0.4, 0.85, 14), position: [0, 0.42, 0] }
  ]);
  const hatGeometry = mergeParts([
    // Brim + slightly inclined cone.
    { geometry: new THREE.CylinderGeometry(0.3, 0.3, 0.04, 16), position: [0, 1.3, 0], rotation: [0, 0, 0.1] },
    { geometry: new THREE.ConeGeometry(0.19, 0.44, 14), position: [0.04, 1.52, 0], rotation: [0, 0, -0.18] }
  ]);
  const ribbonGeometry = mergeParts([
    // Two red ribbons flowing from the brim — costume, never risk.
    {
      geometry: curveTube(
        [
          [0.24, 1.3, 0.08],
          [0.34, 1.12, 0.14],
          [0.3, 0.9, 0.22]
        ],
        0.02
      )
    },
    {
      geometry: curveTube(
        [
          [0.2, 1.3, -0.14],
          [0.3, 1.08, -0.24],
          [0.24, 0.86, -0.3]
        ],
        0.02
      )
    }
  ]);
  const eyeGeometry = mergeParts([
    { geometry: new THREE.SphereGeometry(0.032, 8, 8), position: [-0.1, 1.05, 0.25] },
    { geometry: new THREE.SphereGeometry(0.032, 8, 8), position: [0.1, 1.05, 0.25] }
  ]);

  const furMaterial = new THREE.MeshStandardMaterial({
    color: TAKEZO_PALETTE.fur,
    roughness: 0.85,
    metalness: 0.05,
    emissive: TAKEZO_PALETTE.fur,
    emissiveIntensity: 0.06,
    depthWrite: true
  });
  const robeMaterial = new THREE.MeshStandardMaterial({
    color: TAKEZO_PALETTE.robe,
    roughness: 0.7,
    metalness: 0.1,
    emissive: TAKEZO_PALETTE.robe,
    emissiveIntensity: 0.12,
    depthWrite: true
  });
  const hatMaterial = new THREE.MeshStandardMaterial({
    color: TAKEZO_PALETTE.hat,
    roughness: 0.7,
    metalness: 0.1,
    emissive: TAKEZO_PALETTE.hat,
    emissiveIntensity: 0.12,
    depthWrite: true
  });
  const ribbonMaterial = new THREE.MeshStandardMaterial({
    color: TAKEZO_PALETTE.ribbon,
    roughness: 0.6,
    metalness: 0.05,
    emissive: TAKEZO_PALETTE.ribbon,
    emissiveIntensity: 0.18,
    depthWrite: true
  });
  // Small, discreet emissive eyes.
  const eyeMaterial = new THREE.MeshBasicMaterial({
    color: TAKEZO_PALETTE.eyes,
    toneMapped: false,
    depthWrite: true
  });

  const group = new THREE.Group();
  const meshes = [
    new THREE.Mesh(furGeometry, furMaterial),
    new THREE.Mesh(robeGeometry, robeMaterial),
    new THREE.Mesh(hatGeometry, hatMaterial),
    new THREE.Mesh(ribbonGeometry, ribbonMaterial),
    new THREE.Mesh(eyeGeometry, eyeMaterial)
  ];
  for (const mesh of meshes) {
    mesh.renderOrder = TAKEZO_RENDER_ORDER;
    mesh.frustumCulled = false;
    group.add(mesh);
  }
  return {
    group,
    meshes,
    drawCalls: meshes.length,
    dispose: () => {
      for (const mesh of meshes) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      }
    }
  };
}

// ---------------------------------------------------------------------------
// Choreography (plan §15.3), expressed through the existing motion grammar
// instead of ad-hoc timings: veil (feedback) → chain arc draws (overlay) →
// Takezo materializes (surfaceEnter) → the speech plate appears and receives
// focus. Reduced motion collapses every duration to zero: short CSS fade,
// static character, immediate focus on the plate.

export type TakezoTimeline = {
  veilMs: number;
  chainDelayMs: number;
  chainMs: number;
  wizardDelayMs: number;
  wizardMs: number;
  plateDelayMs: number;
};

export function takezoRitualTimeline(reduced: boolean, speed = DEFAULT_MOTION_SPEED): TakezoTimeline {
  const veilMs = motionDurationMs("feedback", speed, reduced);
  const chainMs = motionDurationMs("overlay", speed, reduced);
  const wizardMs = motionDurationMs("surfaceEnter", speed, reduced);
  return {
    veilMs,
    chainDelayMs: veilMs,
    chainMs,
    wizardDelayMs: veilMs + chainMs,
    wizardMs,
    plateDelayMs: veilMs + chainMs + wizardMs
  };
}

/**
 * The materializing wizard. `animate=false` (reduced motion or a degraded
 * density budget — Takezo is the first layer to degrade) renders the static
 * pose immediately; otherwise the character scales in on the surfaceEnter
 * curve, invalidating frames only while the phase runs.
 */
export function TakezoWizard({
  appearDelayMs,
  durationMs,
  animate
}: {
  appearDelayMs: number;
  durationMs: number;
  animate: boolean;
}) {
  const build = useMemo(() => buildTakezoWizard(), []);
  useEffect(() => () => build.dispose(), [build]);
  const startRef = useRef<number | null>(null);
  const doneRef = useRef(!animate || durationMs <= 0);
  if (doneRef.current) build.group.scale.setScalar(1);
  else if (startRef.current === null) build.group.scale.setScalar(0.001);
  useFrame((state) => {
    if (doneRef.current) return;
    if (startRef.current === null) startRef.current = state.clock.elapsedTime;
    const elapsedMs = (state.clock.elapsedTime - startRef.current) * 1000 - appearDelayMs;
    const progress = Math.min(Math.max(elapsedMs / durationMs, 0), 1);
    build.group.scale.setScalar(Math.max(motionProgress("surfaceEnter", progress), 0.001));
    state.invalidate();
    if (progress >= 1) doneRef.current = true;
  });
  return <primitive object={build.group} />;
}

// ---------------------------------------------------------------------------
// Speech plate content. One DOM body shared by the in-world plate (drei Html)
// and the 2D fallback so both branches always speak the exact same lines.
// The plate respects the SpatialUI singleton: while it is open, the node
// summary WorldPlate is suppressed (one plate at a time).

export type TakezoRuntimeKind = "demo" | "sample" | "local";

export type TakezoSpeechHandlers = {
  runtime: TakezoRuntimeKind;
  onUnlock?: () => void;
  onClose: () => void;
};

const SPEECH_KEY: Record<TakezoRuntimeKind, string> = {
  demo: "takezo.speech.demo",
  sample: "takezo.speech.sample",
  local: "takezo.speech.locked"
};

export function TakezoSpeechContent({ runtime, onUnlock, onClose }: TakezoSpeechHandlers) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  // Focus management (plan §23): the ritual moves keyboard focus onto the
  // plate as soon as it exists; closing hands focus back to the host.
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    onClose();
  };
  return (
    <div
      ref={dialogRef}
      className="takezoPlate"
      role="dialog"
      aria-label={t("takezo.plateAria")}
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <button className="questPlateClose" onClick={onClose} title={t("help.close")} type="button">
        ×
      </button>
      <strong className="takezoName">{t("takezo.name")}</strong>
      <p className="takezoSpeech">{t(SPEECH_KEY[runtime])}</p>
      <small className="takezoNote">{t(`takezo.note.${runtime}`)}</small>
      <div className="takezoActions">
        {runtime === "local" && onUnlock && (
          <button className="plateCta" onClick={onUnlock} type="button">
            {t("takezo.action.unlock")}
          </button>
        )}
        {runtime === "local" ? (
          <>
            <button className="plateGhost" onClick={onClose} type="button">
              {t("takezo.action.explore")}
            </button>
            <button className="plateGhost" onClick={onClose} type="button">
              {t("takezo.action.cancel")}
            </button>
          </>
        ) : (
          <button className="plateGhost" onClick={onClose} type="button">
            {t("takezo.action.leave")}
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The composed in-world ritual: chain portal + wizard + speech plate,
// anchored near the root / camera center. Mounted by SystemScene only while
// the ritual is active; unmounting disposes every geometry and material.

export type TakezoRitualSpec = TakezoSpeechHandlers & {
  /** Reduced motion or an exhausted density budget: static pose, instant plate. */
  reduced: boolean;
  motionSpeed?: number;
};

export function TakezoRitual({
  spec,
  anchor
}: {
  spec: TakezoRitualSpec;
  anchor: [number, number, number];
}) {
  const timeline = useMemo(
    () => takezoRitualTimeline(spec.reduced, spec.motionSpeed ?? DEFAULT_MOTION_SPEED),
    [spec.motionSpeed, spec.reduced]
  );
  const [plateOpen, setPlateOpen] = useState(timeline.plateDelayMs <= 0);
  useEffect(() => {
    if (timeline.plateDelayMs <= 0) {
      setPlateOpen(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setPlateOpen(true), timeline.plateDelayMs);
    return () => window.clearTimeout(timer);
  }, [timeline.plateDelayMs]);
  return (
    <group position={anchor}>
      <TakezoPortal delayMs={timeline.chainDelayMs} durationMs={timeline.chainMs} animate={!spec.reduced} />
      <TakezoWizard appearDelayMs={timeline.wizardDelayMs} durationMs={timeline.wizardMs} animate={!spec.reduced} />
      {plateOpen && (
        <Html
          position={[0, 2.05, 0]}
          center
          distanceFactor={6}
          wrapperClass="sceneHtmlLabel sceneHtmlInteractive"
          className="takezoPlateWrap"
          zIndexRange={[80, 0]}
        >
          <TakezoSpeechContent runtime={spec.runtime} onUnlock={spec.onUnlock} onClose={spec.onClose} />
        </Html>
      )}
    </group>
  );
}
