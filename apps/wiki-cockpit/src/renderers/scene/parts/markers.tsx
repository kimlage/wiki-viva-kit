// In-world event markers: quest markers (missions PLACED over the pages that
// ask for attention, expanding into a small spatial action plate) and birth
// bursts (the light-converge/ignite/shockwave spectacle greeting pages that
// genuinely did not exist in the previous bundle).

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { t } from "../../../data/i18n";
import { contextStyle } from "../../../data/presentation";
import { glowTexture } from "../glow";
import type { LayoutNode } from "../../../scene/layout";

// Quest markers: missions PLACED IN THE WORLD. A small pulsing marker floats over each page that asks for attention
// (stale, a relation past its cadence, missing evidence); hover says WHY,
// click opens the page. Tones reuse the honest accents: amber = needs refresh,
// cyan = verify, purple = evidence. Rendered with the same Html mechanism as
// every scene label, so it is keyboard/screen-reader reachable.
export type MissionMarker = { pageId: string; kind: string; title: string; why: string };

const MARKER_GLYPH: Record<string, string> = { refresh: "!", verify: "?", evidence: "◆", approve: "!" };

export function QuestMarkers({
  nodes,
  markers,
  selectedId,
  onAct,
  onResolve,
  onDismiss
}: {
  nodes: LayoutNode[];
  markers: MissionMarker[];
  selectedId: string;
  onAct: (pageId: string) => void;
  onResolve?: (pageId: string) => void;
  onDismiss?: (pageId: string) => void;
}) {
  // The mission is LIVED at the marker: clicking opens a small spatial menu
  // (what/why + open / resolve-with-Codex / later) — no detour through panels.
  const [openId, setOpenId] = useState<string | null>(null);
  const byId = useMemo(() => {
    const map = new Map<string, LayoutNode>();
    for (const node of nodes) {
      map.set(node.id, node);
      if (node.path) map.set(node.path, node);
    }
    return map;
  }, [nodes]);
  return (
    <>
      {markers.map((marker) => {
        const node = byId.get(marker.pageId);
        if (!node || node.id === selectedId) return null;
        // Anchor at the node's TOP POLE (a point ON the sphere, not in empty
        // space) — the CSS raises the marker by its own height in SCREEN
        // space, so the tip touches the item at every camera angle.
        const lift = Math.max(node.scale, 0.1) * 0.98;
        const open = openId === marker.pageId;
        return (
          <Html
            key={`quest-${marker.pageId}`}
            position={[node.position[0], node.position[1] + lift, node.position[2]]}
            center
            distanceFactor={9}
            wrapperClass="sceneHtmlLabel"
            className="questMarkerWrap"
            zIndexRange={[open ? 55 : 45, 0]}
          >
            {/* The marker EXPANDS INTO the plate (one anchored element — no
                offset math, nothing to misalign). Closing collapses it back.
                anchoredAbove raises by own height: the tip sits ON the node. */}
            <div className={open ? "anchoredAbove" : "anchoredAbove anchoredTight"}>
            {open ? (
              <div className={`questPlate quest-${marker.kind}`} role="menu" aria-label={marker.title}>
                <button
                  className="questPlateClose"
                  onClick={() => setOpenId(null)}
                  title={t("help.close")}
                  type="button"
                >
                  ×
                </button>
                <strong>{marker.title}</strong>
                <small>{marker.why}</small>
                <div className="questMenuActions">
                  <button role="menuitem" onClick={() => { setOpenId(null); onAct(marker.pageId); }} type="button">
                    {t("quest.open")}
                  </button>
                  {onResolve && (
                    <button role="menuitem" onClick={() => { setOpenId(null); onResolve(marker.pageId); }} type="button">
                      {t("quest.resolve")}
                    </button>
                  )}
                  {onDismiss && (
                    <button role="menuitem" className="questLater" onClick={() => { setOpenId(null); onDismiss(marker.pageId); }} type="button">
                      {t("quest.later")}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <button
                className={`questMarker quest-${marker.kind}`}
                onClick={() => setOpenId(marker.pageId)}
                title={`${marker.title} — ${marker.why}`}
                aria-label={`${marker.title} — ${marker.why}`}
                aria-expanded={false}
                type="button"
              >
                <i aria-hidden>{MARKER_GLYPH[marker.kind] ?? "!"}</i>
              </button>
            )}
            </div>
          </Html>
        );
      })}
    </>
  );
}

// Birth bursts: when entities are BORN into the galaxy (a genesis stage
// advance, a future real refetch after a merged PR), creation is an EVENT —
// light converges into the newborn, ignites, and a shockwave rolls out. Pure
// spectacle over honest data: only pages that genuinely did not exist in the
// previous bundle burst. Colors: white flash + the node's own context accent
// (no reserved state accent is touched).
const BIRTH_DURATION = 2.4;
const BIRTH_STAGGER = 0.22;

function easeOutCubicBirth(t: number): number {
  return 1 - (1 - t) ** 3;
}

export function BirthBursts({ nodes, bornIds }: { nodes: LayoutNode[]; bornIds: string[] }) {
  const born = useMemo(() => {
    const wanted = new Set(bornIds);
    return nodes.filter((node) => wanted.has(node.id));
  }, [nodes, bornIds]);
  const [alive, setAlive] = useState(true);
  const startRef = useRef<number | null>(null);
  const flashRefs = useRef<(THREE.Sprite | null)[]>([]);
  const shockRefs = useRef<(THREE.Mesh | null)[]>([]);
  const texture = glowTexture();

  useEffect(() => {
    startRef.current = null;
    setAlive(born.length > 0);
  }, [born]);

  useFrame((state) => {
    if (!alive || born.length === 0) return;
    if (startRef.current === null) startRef.current = state.clock.elapsedTime;
    const elapsed = state.clock.elapsedTime - startRef.current;
    let anyRunning = false;
    born.forEach((node, index) => {
      const local = Math.min(Math.max((elapsed - index * BIRTH_STAGGER) / BIRTH_DURATION, 0), 1);
      if (local < 1) anyRunning = true;
      const flash = flashRefs.current[index];
      if (flash) {
        // Phase 1 (0–0.35): light CONVERGES into the newborn; phase 2: ignition
        // flares and fades. Sized for GALAXY zoom — a birth must read from far.
        const converge = Math.min(local / 0.35, 1);
        const flare = local < 0.35 ? 1 : Math.max(0, 1 - (local - 0.35) / 0.5);
        const size = Math.max(node.scale, 0.16) * (18 - 15.5 * easeOutCubicBirth(converge));
        flash.scale.set(size, size, 1);
        const material = flash.material as THREE.SpriteMaterial;
        material.opacity = local >= 1 ? 0 : 0.35 + 0.65 * flare;
      }
      const shock = shockRefs.current[index];
      if (shock) {
        // The shockwave starts at ignition and rolls outward.
        const wave = Math.min(Math.max((local - 0.3) / 0.7, 0), 1);
        const size = Math.max(node.scale, 0.16) * (0.5 + 14 * easeOutCubicBirth(wave));
        shock.scale.set(size, size, size);
        const material = shock.material as THREE.MeshBasicMaterial;
        material.opacity = wave <= 0 || local >= 1 ? 0 : 0.6 * (1 - wave) ** 1.4;
      }
    });
    state.invalidate();
    if (!anyRunning) setAlive(false);
  });

  if (!alive || born.length === 0 || !texture) return null;
  return (
    <group>
      {born.map((node, index) => (
        <group key={`birth-${node.id}`} position={node.position}>
          <sprite
            ref={(sprite) => {
              flashRefs.current[index] = sprite;
            }}
            scale={[node.scale * 10, node.scale * 10, 1]}
          >
            <spriteMaterial
              map={texture}
              color="#eaf6ff"
              transparent
              opacity={0}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
              toneMapped={false}
            />
          </sprite>
          <mesh
            ref={(mesh) => {
              shockRefs.current[index] = mesh;
            }}
            scale={[0.4, 0.4, 0.4]}
          >
            <sphereGeometry args={[1, 20, 20]} />
            <meshBasicMaterial
              color={contextStyle(node.context).accent}
              wireframe
              transparent
              opacity={0}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </group>
      ))}
    </group>
  );
}
