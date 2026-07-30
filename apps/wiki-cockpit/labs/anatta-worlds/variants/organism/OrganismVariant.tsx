import { PerspectiveCamera } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useState } from "react";
import type { AnattaVariantProps } from "../../contracts";
import { DecisionSurface, IntentionCard, PhaseDots } from "../../shared";
import "./OrganismVariant.css";

const BED_POSITIONS = {
  west: -3.2,
  center: 0,
  east: 3.2
} as const;

type BedProps = {
  positionX: number;
  foliage: string;
  flower: string;
};

function Plant({
  position,
  foliage,
  flower,
  lean = 0
}: {
  position: [number, number, number];
  foliage: string;
  flower: string;
  lean?: number;
}) {
  return (
    <group position={position} rotation={[0, 0, lean]}>
      <mesh position={[0, 0.3, 0]} castShadow>
        <cylinderGeometry args={[0.035, 0.055, 0.62, 6]} />
        <meshStandardMaterial color="#315e46" roughness={0.88} />
      </mesh>
      <mesh position={[-0.13, 0.48, 0]} rotation={[0, 0, -0.55]} castShadow>
        <sphereGeometry args={[0.18, 7, 5]} />
        <meshStandardMaterial color={foliage} roughness={0.9} />
      </mesh>
      <mesh position={[0.13, 0.57, 0]} rotation={[0, 0, 0.5]} castShadow>
        <sphereGeometry args={[0.17, 7, 5]} />
        <meshStandardMaterial color={foliage} roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.78, 0]} castShadow>
        <dodecahedronGeometry args={[0.11, 0]} />
        <meshStandardMaterial color={flower} roughness={0.72} />
      </mesh>
    </group>
  );
}

function BedBase({ positionX, foliage, flower }: BedProps) {
  const plantRows = [-0.88, 0, 0.88] as const;
  return (
    <group position={[positionX, 0, 0]}>
      <mesh position={[0, 0.2, 0]} castShadow receiveShadow>
        <boxGeometry args={[2.25, 0.4, 3.15]} />
        <meshStandardMaterial color="#866044" roughness={0.93} />
      </mesh>
      <mesh position={[0, 0.43, 0]} receiveShadow>
        <boxGeometry args={[1.92, 0.08, 2.82]} />
        <meshStandardMaterial color="#362a22" roughness={1} />
      </mesh>
      {plantRows.flatMap((z, row) =>
        ([-0.5, 0.5] as const).map((x, column) => (
          <Plant
            key={`${row}-${column}`}
            position={[x, 0.45, z]}
            foliage={foliage}
            flower={flower}
            lean={(row + column) % 2 === 0 ? -0.04 : 0.05}
          />
        ))
      )}
    </group>
  );
}

function EastBed({ recovering }: { recovering: boolean }) {
  const foliage = recovering ? "#79c987" : "#918254";
  const flower = recovering ? "#c8f7bd" : "#cf9b61";
  const focus = recovering ? "#7de59b" : "#f3b35b";

  return (
    <group>
      <BedBase
        positionX={BED_POSITIONS.east}
        foliage={foliage}
        flower={flower}
      />
      <mesh position={[BED_POSITIONS.east, 0.08, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[1.84, 1.98, 48]} />
        <meshBasicMaterial color={focus} transparent opacity={recovering ? 0.62 : 0.48} />
      </mesh>
      <group position={[BED_POSITIONS.east + 1.38, 1.25, -0.78]}>
        <mesh castShadow>
          <cylinderGeometry args={[0.11, 0.11, 1.8, 10]} />
          <meshStandardMaterial color="#253c35" roughness={0.84} />
        </mesh>
        <mesh position={[0, 1.05, 0]} castShadow>
          <octahedronGeometry args={[0.29, 0]} />
          <meshStandardMaterial
            color={focus}
            emissive={focus}
            emissiveIntensity={recovering ? 0.24 : 0.12}
            roughness={0.5}
          />
        </mesh>
      </group>
      <mesh
        position={[BED_POSITIONS.east, 0.46, 0]}
        receiveShadow
      >
        <boxGeometry args={[1.91, 0.025, 2.8]} />
        <meshStandardMaterial
          color={recovering ? "#304c39" : "#3e3025"}
          roughness={1}
          transparent
          opacity={recovering ? 0.38 : 0.18}
        />
      </mesh>
    </group>
  );
}

function Reservoir() {
  return (
    <group position={[-4.75, 0, -3.15]}>
      <mesh position={[0, 0.66, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[1.05, 1.22, 1.32, 20]} />
        <meshStandardMaterial color="#3b5554" roughness={0.7} metalness={0.08} />
      </mesh>
      <mesh position={[0, 1.34, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.91, 24]} />
        <meshStandardMaterial
          color="#5da6a5"
          emissive="#244f52"
          emissiveIntensity={0.18}
          roughness={0.32}
        />
      </mesh>
      <mesh position={[1.82, 0.16, 1.52]} rotation={[0, -0.56, 0]} receiveShadow>
        <boxGeometry args={[4.3, 0.12, 0.18]} />
        <meshStandardMaterial color="#406f72" roughness={0.55} />
      </mesh>
    </group>
  );
}

function GardenWorld({ eastRecovering }: { eastRecovering: boolean }) {
  return (
    <>
      <color attach="background" args={["#101a18"]} />
      <fog attach="fog" args={["#101a18", 15, 29]} />
      <ambientLight intensity={0.72} color="#c2d8c7" />
      <hemisphereLight args={["#bad8d5", "#18241c", 1.05]} />
      <directionalLight
        position={[5, 11, 7]}
        intensity={2.2}
        color="#ffe4b2"
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-camera-far={30}
        shadow-camera-left={-10}
        shadow-camera-right={10}
        shadow-camera-top={10}
        shadow-camera-bottom={-10}
      />
      <PerspectiveCamera
        makeDefault
        position={[10.6, 7.4, 10.8]}
        fov={39}
        near={0.1}
        far={45}
        onUpdate={(camera) => camera.lookAt(1.15, 0.55, -0.15)}
      />

      <mesh position={[0, -0.13, 0]} receiveShadow>
        <cylinderGeometry args={[9.2, 9.8, 0.35, 32]} />
        <meshStandardMaterial color="#1f3028" roughness={1} />
      </mesh>
      <mesh position={[0, 0.025, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[8.85, 32]} />
        <meshStandardMaterial color="#263b30" roughness={1} />
      </mesh>

      <BedBase
        positionX={BED_POSITIONS.west}
        foliage="#5f9872"
        flower="#d8cc87"
      />
      <BedBase
        positionX={BED_POSITIONS.center}
        foliage="#6eaa75"
        flower="#c6a6c9"
      />
      <EastBed recovering={eastRecovering} />
      <Reservoir />

      <mesh position={[0, 0.06, 2.18]} receiveShadow>
        <boxGeometry args={[9.1, 0.08, 0.72]} />
        <meshStandardMaterial color="#ab9876" roughness={1} />
      </mesh>
      <mesh position={[0, 0.08, -2.15]} receiveShadow>
        <boxGeometry args={[9.1, 0.1, 0.34]} />
        <meshStandardMaterial color="#344b3d" roughness={1} />
      </mesh>
    </>
  );
}

export default function OrganismVariant({
  session,
  dispatch,
  rendererMode,
  reducedMotion
}: AnattaVariantProps) {
  const [docked, setDocked] = useState(false);
  const eastRecovering = session.mutationCommitted;
  const eastStatus = eastRecovering ? "26% · em recuperação" : "16% · tensão localizada";

  return (
    <main
      className={[
        "organismVariant",
        docked ? "organismVariant--docked" : "organismVariant--anchored",
        reducedMotion ? "organismVariant--reducedMotion" : ""
      ].filter(Boolean).join(" ")}
      data-renderer={rendererMode}
      data-east-state={eastRecovering ? "recovering" : "dry_attention"}
    >
      <section className="organismStage" aria-labelledby="organism-world-title">
        <div
          className="organismWorldViewport"
          role="img"
          aria-label={`Jardim Aurora em perspectiva. Três canteiros e um reservatório. Canteiro Leste: ${eastStatus}.`}
        >
          <Canvas
            aria-hidden="true"
            shadows
            frameloop="demand"
            dpr={[1, 1.5]}
            gl={{
              antialias: true,
              alpha: false,
              powerPreference: "high-performance"
            }}
          >
            <GardenWorld eastRecovering={eastRecovering} />
          </Canvas>
          <div className="organismWorldVignette" aria-hidden="true" />
        </div>

        <div className="organismWorldHeading">
          <span>mundo persistente · foco atual</span>
          <h1 id="organism-world-title">Jardim Aurora</h1>
          <p>
            O contexto 3D permanece presente; a precisão nasce do Canteiro Leste.
          </p>
        </div>

        <div className="organismEastBeacon" aria-label={`Canteiro Leste: ${eastStatus}`}>
          <span aria-hidden="true" />
          <div>
            <small>Canteiro Leste</small>
            <strong>{eastRecovering ? "26%" : "16%"}</strong>
            <em>{eastRecovering ? "em recuperação" : "pedindo atenção"}</em>
          </div>
        </div>

        <div className="organismIntention">
          <IntentionCard
            onInspect={() => dispatch({
              type: "inspect_ref",
              dataRef: "intention.responsible-care"
            })}
          />
        </div>

        <div
          className="organismDecision"
          data-surface-placement={docked ? "docked" : "east-anchor"}
        >
          <div className="organismDecisionHandle">
            <div>
              <span aria-hidden="true" />
              <p>
                <small>{docked ? "dock operacional" : "ancorada ao Leste"}</small>
                <strong>{eastStatus}</strong>
              </p>
            </div>
            <button
              type="button"
              onClick={() => setDocked((current) => !current)}
              aria-pressed={docked}
              aria-label={docked ? "Reancorar superfície no Canteiro Leste" : "Fixar superfície no dock"}
            >
              {docked ? "Voltar ao Leste" : "Fixar no dock"}
            </button>
          </div>
          <DecisionSurface
            session={session}
            dispatch={dispatch}
            title="Decisão do Canteiro Leste"
          />
        </div>

        <div className="organismPhaseRail">
          <span>sessão compartilhada</span>
          <PhaseDots session={session} />
        </div>
      </section>
    </main>
  );
}
