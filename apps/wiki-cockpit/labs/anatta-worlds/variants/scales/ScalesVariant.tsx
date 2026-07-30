import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef, useState } from "react";
import type { PerspectiveCamera } from "three";
import { MathUtils, Vector3 } from "three";
import type { AnattaVariantProps } from "../../contracts";
import {
  ANATTA_FIXTURE,
  phaseLabel
} from "../../model";
import type {
  LensId,
  PrototypePhase
} from "../../model";
import {
  DecisionSurface,
  PhaseDots
} from "../../shared";
import "./ScalesVariant.css";

type ScaleId = "world" | "district" | "interior";

type CameraState = {
  position: readonly [number, number, number];
  target: readonly [number, number, number];
  fov: number;
};

const CAMERA_STATES: Record<ScaleId, CameraState> = {
  world: {
    position: [0, 8.8, 10.8],
    target: [0, -0.2, 0],
    fov: 42
  },
  district: {
    position: [3.15, 4.6, 5.5],
    target: [2.25, 0.05, -0.05],
    fov: 39
  },
  interior: {
    position: [3.65, 2.5, 3.8],
    target: [2.45, 0.15, -0.05],
    fov: 36
  }
};

const SCALE_META: readonly {
  id: ScaleId;
  label: string;
  responsibility: string;
}[] = [
  {
    id: "world",
    label: "Mundo",
    responsibility: "diff e consequência"
  },
  {
    id: "district",
    label: "Distrito",
    responsibility: "lentes e relações"
  },
  {
    id: "interior",
    label: "Interior",
    responsibility: "missão, gate e receipt"
  }
];

function scaleForPhase(phase: PrototypePhase): ScaleId {
  if (phase === "quiet" || phase === "diff_available") return "world";
  if (phase === "tension_focused") return "district";
  if (
    phase === "mutation_committed" ||
    phase === "session_closed"
  ) {
    return "world";
  }
  return "interior";
}

function CameraRig({
  scale,
  reducedMotion
}: {
  scale: ScaleId;
  reducedMotion: boolean;
}) {
  const { camera } = useThree();
  const lookAt = useRef(new Vector3(...CAMERA_STATES.world.target));

  useFrame((_, delta) => {
    const state = CAMERA_STATES[scale];
    const destination = new Vector3(...state.position);
    const destinationTarget = new Vector3(...state.target);
    // 95% of the transition settles in about 375 ms, inside the 250–500 ms contract.
    const alpha = reducedMotion ? 1 : 1 - Math.exp(-8 * delta);

    camera.position.lerp(destination, alpha);
    lookAt.current.lerp(destinationTarget, alpha);
    camera.lookAt(lookAt.current);

    const perspective = camera as PerspectiveCamera;
    if (perspective.isPerspectiveCamera) {
      const nextFov = reducedMotion
        ? state.fov
        : MathUtils.lerp(perspective.fov, state.fov, alpha);
      if (Math.abs(nextFov - perspective.fov) > 0.01) {
        perspective.fov = nextFov;
        perspective.updateProjectionMatrix();
      }
    }
  });

  return null;
}

function PlantCluster({
  position,
  tint = "#a4c781"
}: {
  position: readonly [number, number, number];
  tint?: string;
}) {
  return (
    <group position={position}>
      <mesh castShadow position={[-0.24, 0.28, -0.08]} rotation={[0, 0, -0.14]}>
        <coneGeometry args={[0.12, 0.48, 5]} />
        <meshStandardMaterial color={tint} roughness={0.82} />
      </mesh>
      <mesh castShadow position={[0.04, 0.34, 0.02]} rotation={[0.08, 0, 0.16]}>
        <coneGeometry args={[0.14, 0.58, 5]} />
        <meshStandardMaterial color={tint} roughness={0.82} />
      </mesh>
      <mesh castShadow position={[0.3, 0.26, -0.06]} rotation={[-0.08, 0, 0.12]}>
        <coneGeometry args={[0.11, 0.43, 5]} />
        <meshStandardMaterial color={tint} roughness={0.82} />
      </mesh>
    </group>
  );
}

function GardenBed({
  id,
  position,
  color,
  mutationCommitted,
  onInspect
}: {
  id: "west" | "center" | "east";
  position: readonly [number, number, number];
  color: string;
  mutationCommitted: boolean;
  onInspect: () => void;
}) {
  const isEast = id === "east";
  const soilColor = isEast && mutationCommitted ? "#3e8f73" : color;

  return (
    <group position={position}>
      <mesh
        castShadow
        receiveShadow
        onClick={(event) => {
          event.stopPropagation();
          onInspect();
        }}
      >
        <boxGeometry args={[2.35, 0.3, 1.55]} />
        <meshStandardMaterial
          color={soilColor}
          roughness={0.92}
          metalness={0}
        />
      </mesh>
      <mesh position={[0, 0.17, 0]} receiveShadow>
        <boxGeometry args={[2.12, 0.05, 1.32]} />
        <meshStandardMaterial
          color={isEast && mutationCommitted ? "#285e50" : "#79513a"}
          roughness={1}
        />
      </mesh>
      <PlantCluster
        position={[-0.52, 0.25, -0.12]}
        tint={isEast ? "#9eaf70" : undefined}
      />
      <PlantCluster
        position={[0.52, 0.25, 0.12]}
        tint={isEast ? "#9eaf70" : undefined}
      />

      {isEast && mutationCommitted && (
        <group position={[0, 0.225, 0]}>
          <mesh position={[-0.48, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[0.09, 1.08]} />
            <meshStandardMaterial
              color="#7de0cf"
              emissive="#246f67"
              emissiveIntensity={0.28}
              roughness={0.45}
            />
          </mesh>
          <mesh position={[0.2, 0, 0.08]} rotation={[-Math.PI / 2, 0, 0.12]}>
            <planeGeometry args={[0.075, 0.86]} />
            <meshStandardMaterial
              color="#7de0cf"
              emissive="#246f67"
              emissiveIntensity={0.28}
              roughness={0.45}
            />
          </mesh>
        </group>
      )}
    </group>
  );
}

function RelationBeam({
  position,
  length,
  rotation = 0,
  color
}: {
  position: readonly [number, number, number];
  length: number;
  rotation?: number;
  color: string;
}) {
  return (
    <mesh position={position} rotation={[0, rotation, 0]}>
      <boxGeometry args={[length, 0.025, 0.035]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.55}
        transparent
        opacity={0.72}
      />
    </mesh>
  );
}

function GardenScene({
  scale,
  session,
  dispatch
}: Pick<AnattaVariantProps, "session" | "dispatch"> & { scale: ScaleId }) {
  const relationsVisible = scale === "district";
  const eastRef = session.mutationCommitted
    ? "worldPatch.east-recovering"
    : ANATTA_FIXTURE.tension.id;

  return (
    <>
      <color attach="background" args={["#071510"]} />
      <fog attach="fog" args={["#071510", 12, 25]} />
      <ambientLight intensity={0.7} color="#d7f2df" />
      <directionalLight
        castShadow
        color="#fff1c9"
        intensity={2.2}
        position={[-5, 9, 6]}
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <pointLight color="#68d5b3" intensity={1.1} position={[4.2, 2.2, 1.4]} />

      <group>
        <mesh receiveShadow position={[0, -0.55, 0]}>
          <cylinderGeometry args={[6.45, 5.7, 0.8, 12]} />
          <meshStandardMaterial color="#18382b" roughness={0.96} />
        </mesh>
        <mesh receiveShadow position={[0, -0.11, 0]}>
          <cylinderGeometry args={[5.72, 5.92, 0.14, 12]} />
          <meshStandardMaterial color="#31513b" roughness={0.98} />
        </mesh>

        <mesh receiveShadow position={[0, 0.01, 0]}>
          <boxGeometry args={[1.05, 0.08, 8.2]} />
          <meshStandardMaterial color="#c2ad7c" roughness={1} />
        </mesh>

        <GardenBed
          id="west"
          position={[-2.45, 0.15, 0.45]}
          color="#7f6542"
          mutationCommitted={session.mutationCommitted}
          onInspect={() => dispatch({ type: "inspect_ref", dataRef: "entity.bed-west" })}
        />
        <GardenBed
          id="center"
          position={[0, 0.15, 0.45]}
          color="#6f6840"
          mutationCommitted={session.mutationCommitted}
          onInspect={() => dispatch({ type: "inspect_ref", dataRef: "entity.bed-center" })}
        />
        <GardenBed
          id="east"
          position={[2.45, 0.15, 0.45]}
          color="#92583b"
          mutationCommitted={session.mutationCommitted}
          onInspect={() => dispatch({ type: "inspect_ref", dataRef: eastRef })}
        />

        <group
          position={[-3.55, 0.5, -2.05]}
          onClick={(event) => {
            event.stopPropagation();
            dispatch({ type: "inspect_ref", dataRef: ANATTA_FIXTURE.source.id });
          }}
        >
          <mesh castShadow>
            <cylinderGeometry args={[0.62, 0.76, 1.02, 16]} />
            <meshStandardMaterial color="#416f69" roughness={0.7} />
          </mesh>
          <mesh castShadow position={[0, 0.58, 0]}>
            <cylinderGeometry args={[0.5, 0.62, 0.16, 16]} />
            <meshStandardMaterial color="#79b7a6" roughness={0.52} />
          </mesh>
        </group>

        <group visible={relationsVisible}>
          <RelationBeam
            position={[-0.2, 0.92, -1.45]}
            length={3.75}
            rotation={0.18}
            color="#58d3b2"
          />
          <RelationBeam
            position={[1.45, 0.92, -0.85]}
            length={2.65}
            rotation={-0.3}
            color="#efb35c"
          />
          <mesh position={[-1.9, 0.92, -1.78]}>
            <sphereGeometry args={[0.13, 16, 16]} />
            <meshStandardMaterial
              color="#58d3b2"
              emissive="#58d3b2"
              emissiveIntensity={0.7}
            />
          </mesh>
          <mesh position={[2.55, 0.92, -0.48]}>
            <sphereGeometry args={[0.13, 16, 16]} />
            <meshStandardMaterial
              color="#efb35c"
              emissive="#efb35c"
              emissiveIntensity={0.7}
            />
          </mesh>
        </group>
      </group>
    </>
  );
}

function ScaleBreadcrumbs({
  activeScale,
  onScale,
  selectedId
}: {
  activeScale: ScaleId;
  onScale: (scale: ScaleId) => void;
  selectedId: string;
}) {
  return (
    <div className="awScalesNavigation">
      <nav aria-label="Escala espacial">
        {SCALE_META.map((item, index) => (
          <div key={item.id}>
            <button
              type="button"
              aria-current={activeScale === item.id ? "location" : undefined}
              className={activeScale === item.id ? "active" : ""}
              onClick={() => onScale(item.id)}
            >
              <span>0{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.responsibility}</small>
            </button>
            {index < SCALE_META.length - 1 && <i aria-hidden>›</i>}
          </div>
        ))}
      </nav>
      <p>
        foco preservado <strong>{selectedId}</strong>
      </p>
    </div>
  );
}

function WorldPanel({
  session,
  dispatch,
  onNavigate
}: Pick<AnattaVariantProps, "session" | "dispatch"> & {
  onNavigate: (scale: ScaleId) => void;
}) {
  const isCommitted = session.mutationCommitted;

  return (
    <section className="awScalesPanel awScalesWorldPanel" aria-label="Leitura do mundo">
      <span className="awScalesKicker">escala mundo · diff e consequência</span>
      <h1>{ANATTA_FIXTURE.world.name}</h1>
      <p>{ANATTA_FIXTURE.world.intention}</p>

      <div className="awScalesWorldMetrics">
        <article>
          <span>Oeste</span>
          <strong>31%</strong>
          <small>sem mutação</small>
        </article>
        <article className={isCommitted ? "recovering" : "attention"}>
          <span>Leste</span>
          <strong>{isCommitted ? "26%" : "16%"}</strong>
          <small>{isCommitted ? "em recuperação" : "−15 pp no diff"}</small>
        </article>
        <article>
          <span>chuva observada</span>
          <strong>0 mm</strong>
          <small>previsão não é fato</small>
        </article>
      </div>

      {session.phase === "quiet" && (
        <button
          className="awScalesPrimary"
          type="button"
          onClick={() => dispatch({ type: "show_diff" })}
        >
          Ver diff verificável
        </button>
      )}
      {session.phase === "diff_available" && (
        <div className="awScalesPanelActions">
          <button
            type="button"
            onClick={() => dispatch({
              type: "inspect_ref",
              dataRef: ANATTA_FIXTURE.snapshots.day1.id
            })}
          >
            abrir snapshot
          </button>
          <button
            className="awScalesPrimary"
            type="button"
            onClick={() => dispatch({ type: "focus_tension" })}
          >
            Descer ao distrito
          </button>
        </div>
      )}
      {session.phase === "mutation_committed" && (
        <div className="awScalesPanelActions">
          <button
            type="button"
            onClick={() => dispatch({
              type: "inspect_ref",
              dataRef: "receipt.aurora-001"
            })}
          >
            inspecionar receipt
          </button>
          <button
            className="awScalesPrimary"
            type="button"
            onClick={() => dispatch({ type: "close_session" })}
          >
            Encerrar sessão
          </button>
        </div>
      )}
      {session.phase === "session_closed" && (
        <button
          className="awScalesPrimary"
          type="button"
          onClick={() => dispatch({ type: "reset" })}
        >
          Reiniciar comparação
        </button>
      )}
      {!["quiet", "diff_available", "mutation_committed", "session_closed"].includes(session.phase) && (
        <button
          className="awScalesPrimary"
          type="button"
          onClick={() => onNavigate(scaleForPhase(session.phase))}
        >
          Voltar à etapa ativa
        </button>
      )}
    </section>
  );
}

const LENSES: readonly {
  id: LensId;
  label: string;
  moduleId: string;
  reading: string;
  limit: string;
}[] = [
  {
    id: "hydrology",
    label: "Hidrografia",
    moduleId: ANATTA_FIXTURE.modules.hydrology.id,
    reading: "31% → 16% no Leste",
    limit: "lê umidade; não autoriza"
  },
  {
    id: "climate",
    label: "Clima",
    moduleId: ANATTA_FIXTURE.modules.climate.id,
    reading: "70% de previsão em 6 h",
    limit: "previsão não é chuva"
  }
];

function DistrictPanel({
  session,
  dispatch,
  onNavigate
}: Pick<AnattaVariantProps, "session" | "dispatch"> & {
  onNavigate: (scale: ScaleId) => void;
}) {
  const activateLens = (lens: LensId, dataRef: string) => {
    dispatch({ type: "set_lens", lens });
    dispatch({ type: "inspect_ref", dataRef });
  };

  return (
    <section className="awScalesPanel awScalesDistrictPanel" aria-label="Leitura do distrito">
      <header>
        <div>
          <span className="awScalesKicker">escala distrito · lentes e relações</span>
          <h1>Duas leituras, uma evidência</h1>
        </div>
        <strong className="awScalesTensionId">{ANATTA_FIXTURE.tension.id}</strong>
      </header>

      <div className="awScalesRelation" aria-label="Relação entre fonte, lentes e tensão">
        <button
          type="button"
          onClick={() => dispatch({
            type: "inspect_ref",
            dataRef: ANATTA_FIXTURE.snapshots.day1.id
          })}
        >
          <small>fonte</small>
          <strong>snapshot.day-1</strong>
        </button>
        <i aria-hidden>→</i>
        <div className="awScalesLensPair">
          {LENSES.map((lens) => (
            <button
              type="button"
              key={lens.id}
              className={
                session.activeLens === "compare" || session.activeLens === lens.id
                  ? "active"
                  : ""
              }
              onClick={() => activateLens(lens.id, lens.moduleId)}
            >
              <span>{lens.label}</span>
              <strong>{lens.reading}</strong>
              <small>{lens.limit}</small>
            </button>
          ))}
        </div>
        <i aria-hidden>→</i>
        <button
          type="button"
          className="awScalesTension"
          onClick={() => dispatch({
            type: "inspect_ref",
            dataRef: ANATTA_FIXTURE.tension.id
          })}
        >
          <small>tensão</small>
          <strong>agir × esperar</strong>
        </button>
      </div>

      <div className="awScalesPanelActions">
        <button
          type="button"
          onClick={() => dispatch({ type: "set_lens", lens: "compare" })}
        >
          comparar lentes
        </button>
        {session.phase === "tension_focused" ? (
          <button
            className="awScalesPrimary"
            type="button"
            onClick={() => dispatch({ type: "open_mission" })}
          >
            Entrar na Casa de Decisão
          </button>
        ) : (
          <button
            className="awScalesPrimary"
            type="button"
            onClick={() => onNavigate(scaleForPhase(session.phase))}
          >
            Ir à etapa ativa
          </button>
        )}
      </div>
    </section>
  );
}

function InteriorSurface({
  session,
  dispatch
}: Pick<AnattaVariantProps, "session" | "dispatch">) {
  return (
    <div className="awScalesInterior" role="region" aria-label="Interior 2D da Casa de Decisão">
      <div className="awScalesInteriorIdentity">
        <span>interior 2D · mesma entidade</span>
        <strong>Casa de Decisão</strong>
        <small>{session.selectedId}</small>
      </div>
      <DecisionSurface
        session={session}
        dispatch={dispatch}
        title="Missão · gate · receipt"
      />
    </div>
  );
}

export function ScalesVariant({
  session,
  dispatch,
  rendererMode,
  reducedMotion
}: AnattaVariantProps) {
  const derivedScale = scaleForPhase(session.phase);
  const [activeScale, setActiveScale] = useState<ScaleId>(derivedScale);

  useEffect(() => {
    setActiveScale(derivedScale);
  }, [derivedScale, session.phase]);

  return (
    <main
      className="awScalesVariant"
      data-scale={activeScale}
      data-renderer-mode={rendererMode}
      data-reduced-motion={reducedMotion ? "true" : "false"}
    >
      <ScaleBreadcrumbs
        activeScale={activeScale}
        onScale={setActiveScale}
        selectedId={session.selectedId}
      />

      <div
        className="awScalesCanvas"
        role="img"
        aria-label={`Jardim Aurora em escala ${activeScale}. Somente o Canteiro Leste pode mudar após receipt.`}
      >
        <Canvas
          camera={{
            position: CAMERA_STATES.world.position,
            fov: CAMERA_STATES.world.fov,
            near: 0.1,
            far: 60
          }}
          dpr={[1, 1.5]}
          shadows
          gl={{
            antialias: true,
            powerPreference: "high-performance"
          }}
        >
          <CameraRig scale={activeScale} reducedMotion={reducedMotion} />
          <GardenScene scale={activeScale} session={session} dispatch={dispatch} />
        </Canvas>
      </div>

      <div className="awScalesPhase" aria-live="polite">
        <span>estado compartilhado</span>
        <strong>{phaseLabel(session.phase)}</strong>
        <PhaseDots session={session} />
      </div>

      {activeScale === "world" && (
        <WorldPanel
          session={session}
          dispatch={dispatch}
          onNavigate={setActiveScale}
        />
      )}
      {activeScale === "district" && (
        <DistrictPanel
          session={session}
          dispatch={dispatch}
          onNavigate={setActiveScale}
        />
      )}
      {activeScale === "interior" && (
        <InteriorSurface session={session} dispatch={dispatch} />
      )}
    </main>
  );
}

export default ScalesVariant;
