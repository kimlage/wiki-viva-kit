import { OrbitControls, PerspectiveCamera, Sparkles, Stars } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ACESFilmicToneMapping,
  AdditiveBlending,
  BackSide,
  Color,
  DataTexture,
  LinearFilter,
  MathUtils,
  Mesh,
  MeshStandardMaterial,
  PCFSoftShadowMap,
  Quaternion,
  RedFormat,
  RepeatWrapping,
  SRGBColorSpace,
  UnsignedByteType,
  Vector3
} from "three";
import type { AnattaVariantProps } from "../../contracts";
import { ANATTA_FIXTURE, phaseLabel } from "../../model";
import { DecisionSurface } from "../../shared";
import {
  SAND_PLANET_RADIUS,
  applySandBrush,
  createSandPlanetGeometry,
  sandPlanetDisplacement
} from "./sandMath";
import "./SandVariant.css";

type SandTool = "read" | "shape" | "water";
type BrushPoint = { x: number; y: number; z: number };

const TENSION_DIRECTION = new Vector3(0.64, 0.32, 0.7).normalize();
const TENSION_POSITION = TENSION_DIRECTION.clone().multiplyScalar(
  SAND_PLANET_RADIUS
    + sandPlanetDisplacement(TENSION_DIRECTION.x, TENSION_DIRECTION.y, TENSION_DIRECTION.z)
    + 0.12
);

const SAND_FRAGMENT_PATCH = `
  uniform float uTime;
  uniform float uMutation;
  uniform float uLocalWetness;
  uniform vec3 uBrushPoint;
  uniform vec3 uTensionPoint;
  varying vec3 vSandPosition;

  float sandHash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }

  float sandNoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(sandHash(i), sandHash(i + vec2(1.0, 0.0)), f.x),
      mix(sandHash(i + vec2(0.0, 1.0)), sandHash(i + vec2(1.0)), f.x),
      f.y
    );
  }
`;

function createSandBumpTexture() {
  const size = 256;
  const data = new Uint8Array(size * size);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const grain = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
      const fine = grain - Math.floor(grain);
      const wind = Math.sin(x * 0.34 + Math.sin(y * 0.075) * 2.1) * 0.5 + 0.5;
      data[y * size + x] = Math.round(82 + fine * 98 + wind * 52);
    }
  }
  const texture = new DataTexture(data, size, size, RedFormat, UnsignedByteType);
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.repeat.set(34, 22);
  texture.minFilter = LinearFilter;
  texture.magFilter = LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

function SandPlanet({
  tool,
  brushPoint,
  localWetness,
  mutationCommitted,
  onBrushPoint,
  onWet
}: {
  tool: SandTool;
  brushPoint: BrushPoint;
  localWetness: number;
  mutationCommitted: boolean;
  onBrushPoint: (point: BrushPoint) => void;
  onWet: () => void;
}) {
  const meshRef = useRef<Mesh>(null);
  const shaderRef = useRef<any>(null);
  const dragging = useRef(false);
  const geometry = useMemo(() => createSandPlanetGeometry(), []);
  const bumpTexture = useMemo(() => createSandBumpTexture(), []);
  const brushVector = useMemo(() => new Vector3(), []);

  const material = useMemo(() => {
    const next = new MeshStandardMaterial({
      color: new Color("#bda16a"),
      bumpMap: bumpTexture,
      bumpScale: 0.075,
      roughness: 0.97,
      metalness: 0,
      envMapIntensity: 0.2
    });
    next.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = { value: 0 };
      shader.uniforms.uMutation = { value: 0 };
      shader.uniforms.uLocalWetness = { value: 0 };
      shader.uniforms.uBrushPoint = { value: TENSION_POSITION.clone() };
      shader.uniforms.uTensionPoint = { value: TENSION_DIRECTION.clone() };
      shader.vertexShader = shader.vertexShader
        .replace(
          "#include <common>",
          "#include <common>\nvarying vec3 vSandPosition;"
        )
        .replace(
          "#include <begin_vertex>",
          "#include <begin_vertex>\nvSandPosition = position;"
        );
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <common>", `#include <common>\n${SAND_FRAGMENT_PATCH}`)
        .replace(
          "#include <map_fragment>",
          `
            vec3 sandNormal = normalize(vSandPosition);
            float longitude = atan(sandNormal.z, sandNormal.x);
            float latitude = asin(clamp(sandNormal.y, -1.0, 1.0));
            vec2 sphereUv = vec2(longitude, latitude);
            float windLine = sin(longitude * 31.0 + latitude * 9.0
              + sandNoise(sphereUv * 4.2) * 5.0);
            float ripple = smoothstep(-0.08, 0.9, windLine) * 0.075;
            float grain = sandNoise(sphereUv * 76.0) * 0.1;
            float wetLocal = smoothstep(0.955, 0.995, dot(sandNormal, normalize(uBrushPoint)))
              * uLocalWetness;
            float wetMutation = smoothstep(0.93, 0.995, dot(sandNormal, normalize(uTensionPoint)))
              * uMutation;
            float wetness = clamp(max(wetLocal, wetMutation), 0.0, 1.0);
            vec3 drySand = vec3(0.58, 0.40, 0.20);
            vec3 sunSand = vec3(0.86, 0.69, 0.36);
            vec3 wetSand = vec3(0.24, 0.21, 0.16);
            vec3 sandColor = mix(drySand, sunSand, 0.47 + ripple + grain);
            sandColor = mix(sandColor, wetSand, wetness * 0.75);
            float mica = smoothstep(0.989, 0.999, sandHash(floor(sphereUv * vec2(280.0, 190.0))))
              * (1.0 - wetness) * (0.55 + 0.45 * sin(uTime * 0.65));
            sandColor += vec3(0.93, 0.72, 0.35) * mica * 0.36;
            diffuseColor *= vec4(sandColor, 1.0);
          `
        )
        .replace(
          "#include <roughnessmap_fragment>",
          `
            #include <roughnessmap_fragment>
            vec3 roughNormal = normalize(vSandPosition);
            float shaderWetness = clamp(max(
              smoothstep(0.955, 0.995, dot(roughNormal, normalize(uBrushPoint))) * uLocalWetness,
              smoothstep(0.93, 0.995, dot(roughNormal, normalize(uTensionPoint))) * uMutation
            ), 0.0, 1.0);
            roughnessFactor = mix(roughnessFactor, 0.65, shaderWetness);
          `
        );
      shaderRef.current = shader;
    };
    next.customProgramCacheKey = () => "anatta-sand-planet-material-v1";
    return next;
  }, [bumpTexture]);

  useEffect(() => () => {
    geometry.dispose();
    bumpTexture.dispose();
    material.dispose();
  }, [bumpTexture, geometry, material]);

  useEffect(() => {
    const release = () => { dragging.current = false; };
    window.addEventListener("pointerup", release);
    return () => window.removeEventListener("pointerup", release);
  }, []);

  useFrame((state, delta) => {
    if (!shaderRef.current) return;
    shaderRef.current.uniforms.uTime.value = state.clock.elapsedTime;
    shaderRef.current.uniforms.uLocalWetness.value = MathUtils.damp(
      shaderRef.current.uniforms.uLocalWetness.value,
      localWetness,
      4.5,
      delta
    );
    shaderRef.current.uniforms.uMutation.value = MathUtils.damp(
      shaderRef.current.uniforms.uMutation.value,
      mutationCommitted ? 1 : 0,
      3.6,
      delta
    );
    brushVector.set(brushPoint.x, brushPoint.y, brushPoint.z);
    shaderRef.current.uniforms.uBrushPoint.value.copy(brushVector);
  });

  const applyTool = useCallback((event: ThreeEvent<PointerEvent>) => {
    const point = { x: event.point.x, y: event.point.y, z: event.point.z };
    onBrushPoint(point);
    if (tool === "shape") applySandBrush(geometry, event.point);
    if (tool === "water") onWet();
  }, [geometry, onBrushPoint, onWet, tool]);

  return (
    <mesh
      ref={meshRef}
      geometry={geometry}
      material={material}
      receiveShadow
      castShadow
      onPointerDown={(event) => {
        if (tool === "read") {
          onBrushPoint({ x: event.point.x, y: event.point.y, z: event.point.z });
          return;
        }
        event.stopPropagation();
        dragging.current = true;
        applyTool(event);
      }}
      onPointerMove={(event) => {
        if (tool === "read" || !dragging.current) return;
        event.stopPropagation();
        applyTool(event);
      }}
      onPointerUp={() => { dragging.current = false; }}
      userData={{ dataRef: "world.aurora-sand-planet.style-spike" }}
    />
  );
}

function TensionMarker({ active }: { active: boolean }) {
  const quaternion = useMemo(
    () => new Quaternion().setFromUnitVectors(new Vector3(0, 0, 1), TENSION_DIRECTION),
    []
  );
  return (
    <group position={TENSION_POSITION} quaternion={quaternion}>
      <mesh>
        <torusGeometry args={[0.48, 0.035, 12, 64]} />
        <meshBasicMaterial color={active ? "#9fd4b3" : "#f2bd70"} transparent opacity={0.95} />
      </mesh>
      <pointLight color={active ? "#7fc89a" : "#f0a44a"} intensity={active ? 2.4 : 1.4} distance={4} />
    </group>
  );
}

function SandWorldScene({
  tool,
  brushPoint,
  localWetness,
  mutationCommitted,
  reducedMotion,
  onBrushPoint,
  onWet
}: {
  tool: SandTool;
  brushPoint: BrushPoint;
  localWetness: number;
  mutationCommitted: boolean;
  reducedMotion: boolean;
  onBrushPoint: (point: BrushPoint) => void;
  onWet: () => void;
}) {
  return (
    <>
      <color attach="background" args={["#080b10"]} />
      <fog attach="fog" args={["#17181a", 25, 52]} />
      <PerspectiveCamera makeDefault position={[11.8, 8.4, 14.8]} fov={39} near={0.1} far={100} />
      <Stars radius={52} depth={20} count={1600} factor={2.3} saturation={0.18} fade speed={0.12} />
      <ambientLight color="#5f7180" intensity={0.45} />
      <hemisphereLight args={["#8ea0ad", "#261d15", 0.7]} />
      <directionalLight
        castShadow
        position={[-13, 8, 9]}
        color="#ffd083"
        intensity={4.8}
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-9}
        shadow-camera-right={9}
        shadow-camera-top={9}
        shadow-camera-bottom={-9}
      />
      <SandPlanet
        tool={tool}
        brushPoint={brushPoint}
        localWetness={localWetness}
        mutationCommitted={mutationCommitted}
        onBrushPoint={onBrushPoint}
        onWet={onWet}
      />
      <mesh>
        <sphereGeometry args={[6.72, 96, 64]} />
        <meshBasicMaterial
          color="#d6a85f"
          side={BackSide}
          transparent
          opacity={0.055}
          blending={AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
      <TensionMarker active={mutationCommitted} />
      {!reducedMotion && (
        <Sparkles count={110} scale={[16, 16, 16]} size={1.15} speed={0.06} color="#e9c98a" opacity={0.18} />
      )}
      <OrbitControls
        target={[0, 0, 0]}
        enableDamping={!reducedMotion}
        dampingFactor={0.055}
        enablePan={false}
        minDistance={12.5}
        maxDistance={25}
        minPolarAngle={MathUtils.degToRad(20)}
        maxPolarAngle={MathUtils.degToRad(160)}
      />
    </>
  );
}

function contextualAction(phase: AnattaVariantProps["session"]["phase"]) {
  if (phase === "quiet") return "Revelar a tensão";
  if (phase === "diff_available") return "Focar a região seca";
  return "Abrir mesa de decisão";
}

function planetCoordinates(point: BrushPoint) {
  const vector = new Vector3(point.x, point.y, point.z).normalize();
  const latitude = Math.asin(vector.y) * 180 / Math.PI;
  const longitude = Math.atan2(vector.z, vector.x) * 180 / Math.PI;
  return `${Math.abs(latitude).toFixed(1)}°${latitude >= 0 ? "N" : "S"} · ${Math.abs(longitude).toFixed(1)}°${longitude >= 0 ? "L" : "O"}`;
}

export default function SandVariant({
  session,
  dispatch,
  rendererMode,
  reducedMotion
}: AnattaVariantProps) {
  const [tool, setTool] = useState<SandTool>("read");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [brushPoint, setBrushPoint] = useState<BrushPoint>({
    x: TENSION_POSITION.x,
    y: TENSION_POSITION.y,
    z: TENSION_POSITION.z
  });
  const [localWetness, setLocalWetness] = useState(0);

  const runContextAction = () => {
    if (session.phase === "quiet") {
      dispatch({ type: "show_diff" });
      return;
    }
    if (session.phase === "diff_available") {
      dispatch({ type: "focus_tension" });
      return;
    }
    setDrawerOpen(true);
  };

  const currentMoisture = session.mutationCommitted
    ? 26
    : Math.round(16 + localWetness * 6);

  return (
    <main
      className="sandVariant"
      data-renderer={rendererMode}
      data-sand-tool={tool}
      data-sand-wetness={localWetness.toFixed(2)}
      data-east-state={session.mutationCommitted ? "recovering" : "dry_attention"}
    >
      <section className="sandStage" aria-labelledby="sand-world-title">
        <div className="sandCanvas">
          <Canvas
            shadows
            dpr={[1, reducedMotion ? 1.05 : 1.3]}
            gl={{ antialias: true, alpha: false, powerPreference: "high-performance" }}
            onCreated={({ gl }) => {
              gl.outputColorSpace = SRGBColorSpace;
              gl.toneMapping = ACESFilmicToneMapping;
              gl.toneMappingExposure = 1.04;
              gl.shadowMap.type = PCFSoftShadowMap;
            }}
          >
            <SandWorldScene
              tool={tool}
              brushPoint={brushPoint}
              localWetness={localWetness}
              mutationCommitted={session.mutationCommitted}
              reducedMotion={reducedMotion}
              onBrushPoint={setBrushPoint}
              onWet={() => setLocalWetness((value) => Math.min(1, value + 0.11))}
            />
          </Canvas>
        </div>
        <div className="sandOpticalFrame" aria-hidden="true" />

        <header className="sandIdentity">
          <span>Anatta Worlds · teste planetário de matéria</span>
          <h1 id="sand-world-title">Planeta de Areia</h1>
          <p>
            Um mundo sintético inteiro como relevo contínuo: dunas, umidade e
            consequência visível somente na região autorizada.
          </p>
        </header>

        <div className="sandPhase" aria-live="polite">
          <span>leitura atual</span>
          <strong>{phaseLabel(session.phase)}</strong>
        </div>

        <aside className="sandReading" aria-label="Leitura da região Aurora Leste">
          <span>Aurora Leste</span>
          <strong>{currentMoisture}%</strong>
          <small>{session.mutationCommitted ? "recuperação localizada" : "umidade observada"}</small>
          <button
            type="button"
            onClick={() => dispatch({ type: "inspect_ref", dataRef: session.mutationCommitted ? "snapshot.return" : "snapshot.day-1" })}
          >
            abrir dataRef
          </button>
        </aside>

        <aside className="sandTension">
          <i aria-hidden="true" />
          <div>
            <span>{ANATTA_FIXTURE.tension.title}</span>
            <strong>{session.mutationCommitted ? "26% · recuperação autorizada" : "16% · região seca"}</strong>
          </div>
        </aside>

        <nav className="sandTools" aria-label="Ferramentas do planeta de areia">
          {([
            ["read", "1", "Ler", "inspeciona a região"],
            ["shape", "2", "Modelar", "eleva o heightfield"],
            ["water", "3", "Umedecer", "testa o material"]
          ] as const).map(([id, key, label, note]) => (
            <button
              key={id}
              type="button"
              className={tool === id ? "active" : ""}
              onClick={() => setTool(id)}
            >
              <span>{key}</span>
              <strong>{label}</strong>
              <small>{note}</small>
            </button>
          ))}
        </nav>

        <div className="sandActionRail">
          <div>
            <span>coordenada do gesto</span>
            <strong>{planetCoordinates(brushPoint)}</strong>
          </div>
          <p>spike visual · sem solver granular ou conservação de volume</p>
          <button type="button" onClick={runContextAction}>
            {contextualAction(session.phase)}
          </button>
        </div>

        <p className="sandHint">arraste no planeta para usar a ferramenta · role para aproximar · orbite para explorar</p>

        {drawerOpen && (
          <aside className="sandDecisionDrawer" aria-label="Mesa de decisão do Planeta de Areia">
            <button className="sandDrawerClose" type="button" onClick={() => setDrawerOpen(false)}>
              Fechar mesa
            </button>
            <DecisionSurface session={session} dispatch={dispatch} title="Mesa do Planeta de Areia" />
          </aside>
        )}
      </section>
    </main>
  );
}
