// Reference geometry: the world's static guide lines — level rings/arcs/rays,
// the freshness danger zone, proposal stems, the gate torus and the quadrant
// floor frame. Read-only decoration derived from the layout; no interaction
// besides the labels' own buttons.

import { Html } from "@react-three/drei";
import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { t } from "../../data/i18n";
import { contextStyle, trustColor } from "../../data/presentation";
import { QUADRANT_CENTER_ANGLE, SCENE_FACETS } from "../facets";
import type { GitState } from "../../types";
import type { LayoutNode } from "../layout";
import type { WorldLayout } from "../perspectives";

function circlePoints(radius: number, segments = 96, y = 0): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (let index = 0; index <= segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius));
  }
  return points;
}

function arcPoints(radius: number, start: number, end: number, segments = 32, y = 0): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];
  for (let index = 0; index <= segments; index += 1) {
    const angle = start + ((end - start) * index) / segments;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius));
  }
  return points;
}

function StaticLine({ points, color, opacity }: { points: THREE.Vector3[]; color: string; opacity: number }) {
  const object = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity, toneMapped: false });
    return { line: new THREE.Line(geometry, material), geometry, material };
  }, [color, opacity, points]);
  useEffect(() => {
    return () => {
      object.geometry.dispose();
      object.material.dispose();
    };
  }, [object]);
  return <primitive object={object.line} />;
}

export function WorldGuides({ layout }: { layout: WorldLayout }) {
  const freshness = layout.radial === "freshness";
  const band = layout.rOuter - layout.rInner;
  const deadlineRadius = layout.rInner + band * layout.deadlineF;
  const captionWedge = [...layout.wedges].sort(
    (a, b) => b.endAngle - b.startAngle - (a.endAngle - a.startAngle) || a.context.localeCompare(b.context)
  )[0];
  return (
    <group>
      {layout.guides.map((guide, index) => {
        if (guide.kind === "circle") {
          return <StaticLine key={`guide-${index}`} points={circlePoints(guide.radius)} color={guide.color} opacity={guide.opacity} />;
        }
        if (guide.kind === "arc") {
          return (
            <StaticLine
              key={`guide-${index}`}
              points={arcPoints(guide.radius, guide.start, guide.end, 28)}
              color={guide.color}
              opacity={guide.opacity}
            />
          );
        }
        return (
          <StaticLine
            key={`guide-${index}`}
            points={[
              new THREE.Vector3(Math.cos(guide.angle) * guide.r0, 0, Math.sin(guide.angle) * guide.r0),
              new THREE.Vector3(Math.cos(guide.angle) * guide.r1, 0, Math.sin(guide.angle) * guide.r1)
            ]}
            color={guide.color}
            opacity={guide.opacity}
          />
        );
      })}
      {freshness && (
        <>
          {/* Danger zone: translucent amber past the deadline arc. */}
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.03, 0]}>
            <ringGeometry args={[deadlineRadius, layout.rOuter, 96]} />
            <meshBasicMaterial
              color={trustColor("stale")}
              transparent
              opacity={0.045}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
              toneMapped={false}
              side={THREE.DoubleSide}
            />
          </mesh>
          {[layout.rInner, layout.rInner + band * 0.33, layout.rInner + band, layout.rOuter + 0.02].map((radius) => (
            <StaticLine key={`grid-${radius}`} points={circlePoints(radius)} color="#22303a" opacity={0.28} />
          ))}
          {/* Discrete "sem dados" band: unknown freshness lives here — radius
              never fakes a date that does not exist. The band (and its label)
              only exists when some page actually HAS no date: no data, no
              instrument — a newborn world must not open with audit jargon. */}
          {layout.unknownR !== null && layout.nodes.some((node) => node.freshness_state === "unknown") && (
            <>
              <StaticLine points={circlePoints(layout.unknownR)} color={trustColor("unknown")} opacity={0.3} />
              <Html
                position={[Math.cos(0.35) * (layout.unknownR + 0.1), 0.04, Math.sin(0.35) * (layout.unknownR + 0.1)]}
                center
                distanceFactor={5.2}
                wrapperClass="sceneHtmlLabel"
                className="radarDeadlineCaption"
                zIndexRange={[20, 0]}
              >
                <span>{t("scene.unknownBand")}</span>
              </Html>
            </>
          )}
          {captionWedge && (
            <Html
              position={[
                Math.cos(captionWedge.centerAngle) * (deadlineRadius + 0.12),
                0.04,
                Math.sin(captionWedge.centerAngle) * (deadlineRadius + 0.12)
              ]}
              center
              distanceFactor={5.2}
              wrapperClass="sceneHtmlLabel"
              className="radarDeadlineCaption"
              zIndexRange={[20, 0]}
            >
              <span>{t("scene.deadlineCaption")}</span>
            </Html>
          )}
        </>
      )}
      {layout.wedges.map((wedge) => (
        <group key={`wedge-${wedge.context}`}>
          <StaticLine
            points={[
              new THREE.Vector3(Math.cos(wedge.startAngle) * layout.rInner, 0, Math.sin(wedge.startAngle) * layout.rInner),
              new THREE.Vector3(Math.cos(wedge.startAngle) * layout.rOuter, 0, Math.sin(wedge.startAngle) * layout.rOuter)
            ]}
            color="#22303a"
            opacity={0.18}
          />
          {freshness && (
            <StaticLine
              points={arcPoints(layout.rInner + band * layout.deadlineF, wedge.startAngle + 0.02, wedge.endAngle - 0.02, 28)}
              color={trustColor("stale")}
              opacity={0.4}
            />
          )}
          <StaticLine
            points={arcPoints(layout.rOuter + 0.2, wedge.startAngle + 0.015, wedge.endAngle - 0.015, 32)}
            color={layout.wedgeKind === "context" ? contextStyle(wedge.context).accent : "#4f8fb5"}
            opacity={0.65}
          />
        </group>
      ))}
    </group>
  );
}

export function ProposalStems({ nodes }: { nodes: LayoutNode[] }) {
  const stems = nodes.filter((node) => node.position[1] > 0.05);
  return (
    <group>
      {stems.map((node) => (
        <StaticLine
          key={`stem-${node.id}`}
          points={[new THREE.Vector3(node.position[0], 0, node.position[2]), new THREE.Vector3(...node.position)]}
          color={trustColor("proposal")}
          opacity={0.5}
        />
      ))}
    </group>
  );
}

export function GateRing({ git }: { git: GitState }) {
  const color = git.proposal.is_proposal_branch ? trustColor("proposal") : trustColor("root");
  return (
    <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}>
      <torusGeometry args={[1.05, 0.02, 12, 96]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.8} toneMapped={false} />
    </mesh>
  );
}

// Quadrant frame: four THIN translucent floor squares that make the quadrant
// structure POSITIONAL — architecture, not a modal concept. Neutral HUD blue
// at whisper opacity; the active quadrant's square breathes slightly brighter.
// Each square's placement is DERIVED from the same sector-center angle the
// layout uses to place that facet's NODES — the floor can never disagree with
// the world (a hand-written sign table once put every square in the wrong
// sector: selecting Culture & relations lit the square over Identity & intent pages).
const QUADRANT_SQUARES: { facet: string; sx: 1 | -1; sz: 1 | -1 }[] = SCENE_FACETS.map((facet) => ({
  facet,
  sx: Math.cos(QUADRANT_CENTER_ANGLE[facet]) >= 0 ? 1 : -1,
  sz: Math.sin(QUADRANT_CENTER_ANGLE[facet]) >= 0 ? 1 : -1
}));

export function QuadrantPlanes({ rOuter, activeQuadrant }: { rOuter: number; activeQuadrant?: string }) {
  const size = rOuter + 0.9;
  const gap = 0.14;
  return (
    <group position={[0, -0.42, 0]}>
      {QUADRANT_SQUARES.map(({ facet, sx, sz }) => {
        const active = activeQuadrant === facet;
        const half = (size - gap) / 2;
        return (
          <group key={facet} position={[sx * (half + gap / 2 + gap / 2), 0, sz * (half + gap / 2 + gap / 2)]}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[size - gap, size - gap]} />
              <meshBasicMaterial
                color={active ? "#6ea6c4" : "#4a708a"}
                transparent
                opacity={active ? 0.1 : 0.045}
                depthWrite={false}
                toneMapped={false}
                side={THREE.DoubleSide}
              />
            </mesh>
            {/* The thin edge that makes the square READ as a frame. */}
            <lineSegments rotation={[-Math.PI / 2, 0, 0]}>
              <edgesGeometry args={[new THREE.PlaneGeometry(size - gap, size - gap)]} />
              <lineBasicMaterial
                color={active ? "#8fc4e0" : "#3f5a6e"}
                transparent
                opacity={active ? 0.5 : 0.22}
                toneMapped={false}
              />
            </lineSegments>
          </group>
        );
      })}
    </group>
  );
}
