import { Html, Line, MapControls, OrthographicCamera } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { ThreeEvent } from "@react-three/fiber";
import type { OrbitControls as MapControlsImpl } from "three-stdlib";
import type { AnattaVariantProps } from "../../contracts";
import { ANATTA_FIXTURE } from "../../model";
import { DecisionSurface, PhaseDots } from "../../shared";
import "./table.css";

type TableSceneProps = Pick<
  AnattaVariantProps,
  "session" | "dispatch" | "reducedMotion"
>;

type BedSpec = {
  id: "entity.bed-west" | "entity.bed-center" | "entity.bed-east";
  label: "Oeste" | "Centro" | "Leste";
  position: [number, number, number];
  value: string;
  state: string;
  soil: string;
  contour: string;
};

const TABLE_WIDTH = 18;
const TABLE_DEPTH = 11;
const TABLE_Y = 0.12;

const HYDROLOGY_CHANNELS: readonly {
  id: string;
  points: readonly [number, number, number][];
}[] = [
  {
    id: "channel.reservoir-west",
    points: [[-7.15, 0.66, 2.95], [-6.35, 0.7, 1.4], [-6.35, 0.71, -1.45]]
  },
  {
    id: "channel.reservoir-center",
    points: [[-7.15, 0.66, 2.95], [-4.7, 0.7, 1.35], [-3.35, 0.71, -1.45]]
  },
  {
    id: "channel.reservoir-east",
    points: [[-7.15, 0.66, 2.95], [-3.3, 0.7, 1.1], [-0.35, 0.71, -1.45]]
  }
] as const;

const CLIMATE_CURVE: readonly [number, number, number][] = [
  [-7.4, 0.78, -3.7],
  [-5.8, 0.82, -3.15],
  [-4.1, 0.8, -3.4],
  [-2.4, 0.83, -3.05],
  [-0.45, 0.8, -3.35],
  [1.15, 0.79, -2.85]
] as const;

function stopPropagation(event: ThreeEvent<MouseEvent>) {
  event.stopPropagation();
}

function BoundedTableControls({
  reducedMotion,
  compact
}: {
  reducedMotion: boolean;
  compact: boolean;
}) {
  const controls = useRef<MapControlsImpl>(null);
  const camera = useThree((state) => state.camera);

  useFrame(() => {
    const instance = controls.current;
    if (!instance) return;
    const target = instance.target;
    const clampedX = THREE.MathUtils.clamp(target.x, compact ? -4.5 : -2.4, compact ? 4.5 : 2.4);
    const clampedZ = THREE.MathUtils.clamp(target.z, -1.7, 1.7);
    const deltaX = clampedX - target.x;
    const deltaZ = clampedZ - target.z;
    if (deltaX === 0 && deltaZ === 0) return;
    target.x = clampedX;
    target.z = clampedZ;
    camera.position.x += deltaX;
    camera.position.z += deltaZ;
    instance.update();
  });

  return (
    <MapControls
      ref={controls}
      makeDefault
      enableDamping={!reducedMotion}
      dampingFactor={0.08}
      enablePan
      enableRotate
      enableZoom
      minZoom={compact ? 22 : 38}
      maxZoom={compact ? 76 : 88}
      minPolarAngle={0.68}
      maxPolarAngle={1.08}
      minAzimuthAngle={-0.62}
      maxAzimuthAngle={0.62}
      screenSpacePanning={false}
      target={compact ? [3.35, 0.15, 0] : [-0.8, 0.15, 0]}
    />
  );
}

function EngravedLabel({
  position,
  title,
  value,
  state,
  tone = "neutral"
}: {
  position: [number, number, number];
  title: string;
  value: string;
  state: string;
  tone?: "neutral" | "attention" | "recovering" | "water";
}) {
  return (
    <Html
      transform
      center
      position={position}
      rotation={[-Math.PI / 2, 0, 0]}
      scale={0.48}
      zIndexRange={[4, 1]}
    >
      <div className={`awTableMark ${tone}`}>
        <span>{title}</span>
        <strong>{value}</strong>
        <small>{state}</small>
      </div>
    </Html>
  );
}

function Contours({
  center,
  radius,
  color
}: {
  center: [number, number, number];
  radius: number;
  color: string;
}) {
  const rings = useMemo(
    () => [0.66, 0.84, 1].map((ratio) => {
      const points: [number, number, number][] = [];
      for (let step = 0; step <= 40; step += 1) {
        const angle = (step / 40) * Math.PI * 2;
        points.push([
          center[0] + Math.cos(angle) * radius * ratio,
          center[1],
          center[2] + Math.sin(angle) * radius * ratio * 0.54
        ]);
      }
      return points;
    }),
    [center, radius]
  );

  return (
    <group name="typed-moisture-contours" userData={{ dataRef: ANATTA_FIXTURE.snapshots.day1.id }}>
      {rings.map((points, index) => (
        <Line
          key={index}
          points={points}
          color={color}
          lineWidth={index === rings.length - 1 ? 1.35 : 0.75}
          transparent
          opacity={0.72 - index * 0.12}
        />
      ))}
    </group>
  );
}

function GardenBed({
  bed,
  changed,
  onInspect
}: {
  bed: BedSpec;
  changed: boolean;
  onInspect: (dataRef: string) => void;
}) {
  const isEast = bed.id === "entity.bed-east";
  const eastChanged = isEast && changed;
  const soil = eastChanged ? "#326b55" : bed.soil;
  const contour = eastChanged ? "#6ff0ba" : bed.contour;
  const dataRef = eastChanged ? "worldPatch.east-recovering" : bed.id;

  return (
    <group
      name={bed.id}
      position={bed.position}
      userData={{ dataRef }}
      onClick={(event) => {
        stopPropagation(event);
        onInspect(dataRef);
      }}
    >
      <mesh castShadow receiveShadow position={[0, 0.08, 0]}>
        <boxGeometry args={[2.5, 0.46, 2.55]} />
        <meshStandardMaterial color="#122622" roughness={0.88} metalness={0.04} />
      </mesh>
      <mesh castShadow receiveShadow position={[0, 0.34, 0]}>
        <boxGeometry args={[2.18, 0.2, 2.22]} />
        <meshStandardMaterial color={soil} roughness={0.96} metalness={0} />
      </mesh>
      <Contours
        center={[0, 0.47, 0]}
        radius={eastChanged ? 1.04 : isEast ? 0.72 : bed.label === "Oeste" ? 1.08 : 0.94}
        color={contour}
      />
      <EngravedLabel
        position={[0, 0.52, 0]}
        title={`Canteiro ${bed.label}`}
        value={eastChanged ? "26%" : bed.value}
        state={eastChanged ? "em recuperação" : bed.state}
        tone={eastChanged ? "recovering" : isEast ? "attention" : "neutral"}
      />
    </group>
  );
}

function Reservoir({ onInspect }: { onInspect: (dataRef: string) => void }) {
  return (
    <group
      name="source-reservoir"
      position={[-7.15, 0.58, 3]}
      userData={{ dataRef: ANATTA_FIXTURE.source.id }}
      onClick={(event) => {
        stopPropagation(event);
        onInspect(ANATTA_FIXTURE.source.id);
      }}
    >
      <mesh castShadow receiveShadow>
        <cylinderGeometry args={[0.86, 1.05, 0.62, 32]} />
        <meshStandardMaterial color="#0d353a" roughness={0.35} metalness={0.42} />
      </mesh>
      <mesh position={[0, 0.33, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.76, 32]} />
        <meshStandardMaterial color="#3ac6cf" emissive="#0a6970" emissiveIntensity={0.45} roughness={0.18} />
      </mesh>
      <EngravedLabel
        position={[0, 0.42, 1.18]}
        title="reservatório"
        value="62%"
        state="snapshot.day-1"
        tone="water"
      />
    </group>
  );
}

function TypedChannels({ onInspect }: { onInspect: (dataRef: string) => void }) {
  return (
    <>
      <group
        name="hydrology-channels"
        userData={{ dataRef: ANATTA_FIXTURE.modules.hydrology.id }}
        onClick={(event) => {
          stopPropagation(event);
          onInspect(ANATTA_FIXTURE.modules.hydrology.id);
        }}
      >
        {HYDROLOGY_CHANNELS.map((channel) => (
          <Line
            key={channel.id}
            points={channel.points}
            color="#4bd6df"
            lineWidth={2.1}
            transparent
            opacity={0.76}
          />
        ))}
      </group>
      <Line
        name="climate-forecast-curve"
        userData={{ dataRef: ANATTA_FIXTURE.modules.climate.id }}
        points={CLIMATE_CURVE}
        color="#c2a6ff"
        lineWidth={1.4}
        dashed
        dashSize={0.22}
        gapSize={0.13}
        transparent
        opacity={0.82}
        onClick={(event) => {
          stopPropagation(event);
          onInspect(ANATTA_FIXTURE.modules.climate.id);
        }}
      />
      <Html
        transform
        position={[-5.7, 0.83, -4.1]}
        rotation={[-Math.PI / 2, 0, 0]}
        scale={0.42}
        zIndexRange={[3, 1]}
      >
        <div className="awTableEtchedLegend">
          <span><i className="hydro" /> canal observado</span>
          <span><i className="climate" /> previsão · não chuva</span>
        </div>
      </Html>
    </>
  );
}

function DecisionInlayPlate() {
  return (
    <group
      name="decision-inlay-plate"
      position={[4.55, TABLE_Y + 0.28, 0.12]}
      userData={{ dataRef: "surface.decision-table" }}
    >
      <mesh receiveShadow position={[0, -0.04, 0]}>
        <boxGeometry args={[7.25, 0.18, 8.85]} />
        <meshStandardMaterial color="#071b1b" roughness={0.5} metalness={0.42} />
      </mesh>
      <mesh position={[0, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[7.05, 8.62]} />
        <meshStandardMaterial
          color="#0a2524"
          emissive="#092c2b"
          emissiveIntensity={0.26}
          roughness={0.34}
          metalness={0.22}
          transparent
          opacity={0.98}
        />
      </mesh>
      <EngravedLabel
        position={[0, 0.085, 0]}
        title="mesa de decisão"
        value="ativa"
        state="mesmo estado · projeção à direita"
        tone="water"
      />
    </group>
  );
}

function TableScene({ session, dispatch, reducedMotion }: TableSceneProps) {
  const compact = useThree((state) => state.size.width < 700);
  const beds: readonly BedSpec[] = [
    {
      id: "entity.bed-west",
      label: "Oeste",
      position: [-6.35, TABLE_Y + 0.22, -1.45],
      value: "31%",
      state: "sem mutação",
      soil: "#4f5d35",
      contour: "#b9d886"
    },
    {
      id: "entity.bed-center",
      label: "Centro",
      position: [-3.35, TABLE_Y + 0.22, -1.45],
      value: "estável",
      state: "sem mutação",
      soil: "#445c3d",
      contour: "#9bc6a0"
    },
    {
      id: "entity.bed-east",
      label: "Leste",
      position: [-0.35, TABLE_Y + 0.22, -1.45],
      value: "16%",
      state: "tensão localizada",
      soil: "#66502d",
      contour: "#ffc66f"
    }
  ] as const;
  const inspect = (dataRef: string) => dispatch({ type: "inspect_ref", dataRef });

  return (
    <>
      <color attach="background" args={["#030c0c"]} />
      <fog attach="fog" args={["#030c0c", 18, 34]} />
      <OrthographicCamera
        makeDefault
        position={compact ? [14.75, 13.2, 13.8] : [10.6, 13.2, 13.8]}
        zoom={52}
        near={0.1}
        far={80}
      />
      <BoundedTableControls reducedMotion={reducedMotion} compact={compact} />

      <ambientLight intensity={1.15} color="#c7efe5" />
      <hemisphereLight args={["#d6fff4", "#0b1712", 1.2]} />
      <directionalLight
        castShadow
        color="#fff0cd"
        intensity={2.8}
        position={[-7, 12, 7]}
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-camera-left={-12}
        shadow-camera-right={12}
        shadow-camera-top={10}
        shadow-camera-bottom={-10}
      />
      <pointLight color="#44d9d1" intensity={9} distance={15} position={[5, 5, 2]} />

      <group name="anatta-topographic-table">
        <mesh castShadow receiveShadow position={[0, -0.38, 0]}>
          <boxGeometry args={[TABLE_WIDTH + 0.8, 0.84, TABLE_DEPTH + 0.8]} />
          <meshStandardMaterial color="#071312" roughness={0.48} metalness={0.55} />
        </mesh>
        <mesh castShadow receiveShadow position={[0, TABLE_Y - 0.14, 0]}>
          <boxGeometry args={[TABLE_WIDTH, 0.24, TABLE_DEPTH]} />
          <meshStandardMaterial color="#1b3b33" roughness={0.76} metalness={0.18} />
        </mesh>
        <mesh receiveShadow position={[-3.85, TABLE_Y, 0]}>
          <boxGeometry args={[9.5, 0.12, 9.4]} />
          <meshStandardMaterial color="#152c26" roughness={0.94} metalness={0.02} />
        </mesh>

        <Reservoir onInspect={inspect} />
        <TypedChannels onInspect={inspect} />
        {beds.map((bed) => (
          <GardenBed
            key={bed.id}
            bed={bed}
            changed={session.mutationCommitted}
            onInspect={inspect}
          />
        ))}
        <DecisionInlayPlate />
      </group>
    </>
  );
}

export function TableVariant({
  session,
  dispatch,
  rendererMode,
  reducedMotion
}: AnattaVariantProps) {
  return (
    <main
      className="awTableVariant"
      data-renderer-mode={rendererMode}
      data-phase={session.phase}
      data-east-state={session.mutationCommitted ? "recovering" : "attention"}
      aria-label="Variante B: mesa topográfica do Jardim Aurora"
    >
      <Canvas
        shadows
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: false, powerPreference: "high-performance" }}
        onPointerMissed={() => dispatch({ type: "inspect_ref", dataRef: null })}
        aria-label="Mesa topográfica manipulável com três canteiros e superfície de decisão integrada"
      >
        <TableScene
          session={session}
          dispatch={dispatch}
          reducedMotion={reducedMotion}
        />
      </Canvas>
      <section className="awTableProjection" aria-label="Superfície de decisão conectada à mesa">
        <div className="awTableProjectionHeading">
          <span>inlay da mesa · coordenadas de tela legíveis</span>
          <PhaseDots session={session} />
        </div>
        <DecisionSurface
          session={session}
          dispatch={dispatch}
          title="Mesa de decisão"
        />
      </section>
      <div className="awTableInstructions" aria-hidden="true">
        <span>arraste para mover</span>
        <span>pinça/roda para aproximar</span>
        <span>arraste secundário para inclinar</span>
      </div>
      <p className="awTableStatus" role="status">
        {session.mutationCommitted
          ? "Receipt aplicado: somente o Canteiro Leste mudou para 26%, em recuperação."
          : "Estado verificado: Leste em 16%; Oeste e Centro permanecem sem mutação."}
      </p>
    </main>
  );
}

export default TableVariant;
