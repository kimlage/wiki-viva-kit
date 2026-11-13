import {
  ContactShadows,
  Environment,
  Html,
  OrbitControls,
  PerspectiveCamera,
  Sparkles,
  useGLTF,
  useTexture
} from "@react-three/drei";
import { addAfterEffect, useFrame, useThree } from "@react-three/fiber";
import {
  Bloom,
  EffectComposer,
  HueSaturation,
  SSAO,
  Vignette
} from "@react-three/postprocessing";
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  DynamicDrawUsage,
  Euler,
  LinearFilter,
  MathUtils,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  RepeatWrapping,
  ShaderMaterial,
  SRGBColorSpace,
  Vector3
} from "three";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef } from "react";
import {
  BASIN_DEPTH,
  BASIN_WIDTH,
  createMainRiverSamples,
  createRibbonGeometry,
  createTerrainGeometry,
  createTributarySamples,
  riverCenterX,
  riverHalfWidth,
  riverSurfaceY,
  seeded,
  terrainHeight
} from "./sceneMath";

export type BeautyViewMode = "exterior" | "approaching" | "interior";

export type BeautyMetrics = {
  fps: number;
  frameMs: number;
  calls: number;
  triangles: number;
  geometries: number;
  textures: number;
  firstFrameMs: number;
};

type BasinSceneProps = {
  viewMode: BeautyViewMode;
  authorized: boolean;
  receiptVisible: boolean;
  reducedMotion: boolean;
  consoleContent: ReactNode;
  onEnter: () => void;
  onExit: () => void;
  onSelectTension: () => void;
  onMetrics: (metrics: BeautyMetrics) => void;
  onInteriorReached: () => void;
};

const HERO_POSITION = new Vector3(-5.2, 15.2, 17.8);
const HERO_TARGET = new Vector3(0.35, 1.2, -2.8);
const MODULE_X = 4.15;
const MODULE_Z = 0.65;
const MODULE_Y = terrainHeight(MODULE_X, MODULE_Z) + 0.72;
const APPROACH_POSITION = new Vector3(MODULE_X + 1.4, MODULE_Y + 2.05, MODULE_Z + 4.2);
const INTERIOR_POSITION = new Vector3(MODULE_X + 0.15, MODULE_Y + 1.75, MODULE_Z + 1.5);
const INTERIOR_TARGET = new Vector3(MODULE_X, MODULE_Y + 1.35, MODULE_Z - 1.1);

const ASSET_ROOT = "/assets/anatta-beauty";
const ENVIRONMENT_MAP = `${ASSET_ROOT}/overcast-soil-512.hdr`;

function disposeGeometry(geometry: BufferGeometry) {
  return () => geometry.dispose();
}

function CameraDirector({
  mode,
  reducedMotion,
  onInteriorReached
}: {
  mode: BeautyViewMode;
  reducedMotion: boolean;
  onInteriorReached: () => void;
}) {
  const camera = useThree((state) => state.camera);
  const orbitRef = useRef<any>(null);
  const targetPosition = useRef(HERO_POSITION.clone());
  const targetLookAt = useRef(HERO_TARGET.clone());
  const currentLookAt = useRef(HERO_TARGET.clone());
  const arrivedRef = useRef(false);

  useEffect(() => {
    arrivedRef.current = false;
    if (mode === "exterior") {
      targetPosition.current.copy(HERO_POSITION);
      targetLookAt.current.copy(HERO_TARGET);
      camera.position.copy(HERO_POSITION);
      currentLookAt.current.copy(HERO_TARGET);
      camera.lookAt(HERO_TARGET);
      if (orbitRef.current) {
        orbitRef.current.target.copy(HERO_TARGET);
        orbitRef.current.update();
      }
    } else if (mode === "approaching") {
      targetPosition.current.copy(APPROACH_POSITION);
      targetLookAt.current.set(MODULE_X, MODULE_Y + 1.1, MODULE_Z - 0.25);
    } else {
      targetPosition.current.copy(INTERIOR_POSITION);
      targetLookAt.current.copy(INTERIOR_TARGET);
    }
    if (reducedMotion && mode !== "exterior") {
      camera.position.copy(targetPosition.current);
      currentLookAt.current.copy(targetLookAt.current);
      camera.lookAt(currentLookAt.current);
      if (mode === "interior") onInteriorReached();
    }
  }, [camera, mode, onInteriorReached, reducedMotion]);

  useFrame((_, delta) => {
    if (mode === "exterior" && orbitRef.current) {
      currentLookAt.current.copy(orbitRef.current.target);
      return;
    }
    const damping = reducedMotion ? 1 : 1 - Math.exp(-delta * (mode === "approaching" ? 3.6 : 4.4));
    camera.position.lerp(targetPosition.current, damping);
    currentLookAt.current.lerp(targetLookAt.current, damping);
    camera.lookAt(currentLookAt.current);
    if (
      mode === "interior"
      && !arrivedRef.current
      && camera.position.distanceTo(targetPosition.current) < 0.035
    ) {
      arrivedRef.current = true;
      onInteriorReached();
    }
  });

  return (
    <OrbitControls
      ref={orbitRef}
      enabled={mode === "exterior"}
      target={HERO_TARGET}
      enableDamping
      dampingFactor={0.06}
      enablePan={false}
      minDistance={21}
      maxDistance={30}
      minPolarAngle={MathUtils.degToRad(42)}
      maxPolarAngle={MathUtils.degToRad(58)}
      minAzimuthAngle={MathUtils.degToRad(-35)}
      maxAzimuthAngle={MathUtils.degToRad(8)}
    />
  );
}

function configureTexture(texture: any, repeat: [number, number], srgb = false) {
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.repeat.set(repeat[0], repeat[1]);
  texture.minFilter = LinearFilter;
  if (srgb) texture.colorSpace = SRGBColorSpace;
  texture.needsUpdate = true;
}

function Terrain() {
  const meshRef = useRef<Mesh>(null);
  const [
    groundMap,
    groundNormal,
    groundArm,
    rockMap
  ] = useTexture([
    `${ASSET_ROOT}/ground-diff.webp`,
    `${ASSET_ROOT}/ground-normal.webp`,
    `${ASSET_ROOT}/ground-arm.webp`,
    `${ASSET_ROOT}/rock-diff.webp`
  ]);
  useMemo(() => {
    configureTexture(groundMap, [9, 8], true);
    configureTexture(groundNormal, [9, 8]);
    configureTexture(groundArm, [9, 8]);
    configureTexture(rockMap, [1, 1], true);
  }, [groundArm, groundMap, groundNormal, rockMap]);

  const geometry = useMemo(() => createTerrainGeometry(), []);
  useEffect(() => disposeGeometry(geometry), [geometry]);

  const material = useMemo(() => {
    const next = new MeshStandardMaterial({
      map: groundMap,
      normalMap: groundNormal,
      roughnessMap: groundArm,
      vertexColors: true,
      roughness: 0.92,
      metalness: 0,
      envMapIntensity: 0.62
    });
    next.onBeforeCompile = (shader: any) => {
      shader.uniforms.uRockMap = { value: rockMap };
      shader.vertexShader = shader.vertexShader
        .replace(
          "#include <common>",
          "#include <common>\nvarying vec3 vTerrainPosition;\nvarying vec3 vTerrainNormal;"
        )
        .replace(
          "#include <begin_vertex>",
          "#include <begin_vertex>\nvTerrainPosition = position;\nvTerrainNormal = normalize(normal);"
        );
      shader.fragmentShader = shader.fragmentShader
        .replace(
          "#include <common>",
          "#include <common>\nuniform sampler2D uRockMap;\nvarying vec3 vTerrainPosition;\nvarying vec3 vTerrainNormal;"
        )
        .replace(
          "#include <map_fragment>",
          `
          #ifdef USE_MAP
            vec4 sampledDiffuseColor = texture2D(map, vMapUv);
            vec3 weights = pow(abs(normalize(vTerrainNormal)), vec3(5.0));
            weights /= max(weights.x + weights.y + weights.z, 0.0001);
            vec3 rockX = texture2D(uRockMap, vTerrainPosition.zy * 0.115).rgb;
            vec3 rockY = texture2D(uRockMap, vTerrainPosition.xz * 0.115).rgb;
            vec3 rockZ = texture2D(uRockMap, vTerrainPosition.xy * 0.115).rgb;
            vec3 rockColor = rockX * weights.x + rockY * weights.y + rockZ * weights.z;
            float rockLuma = dot(rockColor, vec3(0.299, 0.587, 0.114));
            rockColor = mix(vec3(rockLuma) * vec3(0.76, 0.79, 0.75), rockColor, 0.28);
            float slope = 1.0 - abs(normalize(vTerrainNormal).y);
            float moisture = 1.0 - smoothstep(1.3, 5.2, abs(vTerrainPosition.x));
            float rockBlend = smoothstep(0.045, 0.29, slope);
            rockBlend = clamp(rockBlend + smoothstep(4.2, 6.8, vTerrainPosition.y) * 0.42, 0.0, 0.98);
            sampledDiffuseColor.rgb *= mix(vec3(0.62, 0.69, 0.59), vec3(0.48, 0.57, 0.49), moisture * 0.22);
            diffuseColor *= vec4(mix(sampledDiffuseColor.rgb, rockColor, rockBlend), sampledDiffuseColor.a);
          #endif
          `
        );
    };
    next.customProgramCacheKey = () => "anatta-terrain-triplanar-v2";
    return next;
  }, [groundArm, groundMap, groundNormal, rockMap]);
  useEffect(() => () => material.dispose(), [material]);

  return (
    <mesh
      ref={meshRef}
      geometry={geometry}
      material={material}
      receiveShadow
      castShadow
      userData={{ dataRef: "world.aurora-basin" }}
    />
  );
}

const FLOW_VERTEX = `
  attribute float aEdge;
  attribute float aRapid;
  varying vec2 vUv;
  varying float vEdge;
  varying float vRapid;
  varying vec3 vWorldPosition;
  uniform float uTime;
  uniform float uMotion;
  void main() {
    vUv = uv;
    vEdge = aEdge;
    vRapid = aRapid;
    vec3 transformed = position;
    transformed.y += sin(uv.y * 62.0 - uTime * 2.4) * 0.016 * uMotion;
    vec4 worldPosition = modelMatrix * vec4(transformed, 1.0);
    vWorldPosition = worldPosition.xyz;
    gl_Position = projectionMatrix * viewMatrix * worldPosition;
  }
`;

const FLOW_FRAGMENT = `
  varying vec2 vUv;
  varying float vEdge;
  varying float vRapid;
  varying vec3 vWorldPosition;
  uniform float uTime;
  uniform float uMotion;
  uniform float uAuthorized;
  uniform float uOpacity;
  uniform sampler2D uNormalMapA;
  uniform sampler2D uNormalMapB;
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
  }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash21(i), hash21(i + vec2(1., 0.)), f.x),
               mix(hash21(i + vec2(0., 1.)), hash21(i + vec2(1., 1.)), f.x), f.y);
  }
  void main() {
    float time = uTime * uMotion;
    vec2 flowA = vec2(vUv.x * 3.8 + time * 0.045, vUv.y * 28.0 - time * 0.34);
    vec2 flowB = vec2(vUv.x * 5.4 - time * 0.03, vUv.y * 41.0 - time * 0.22);
    vec3 normalA = texture2D(uNormalMapA, flowA).xyz * 2.0 - 1.0;
    vec3 normalB = texture2D(uNormalMapB, flowB).xyz * 2.0 - 1.0;
    float ripple = clamp((normalA.y + normalB.x) * 0.5 + 0.5, 0.0, 1.0);
    float n1 = noise(vec2(vUv.x * 9.0, vUv.y * 96.0 - time * 1.55));
    float n2 = noise(vec2(vUv.x * 18.0 + 8.0, vUv.y * 168.0 - time * 2.25));
    float streak = smoothstep(0.84, 0.98, n1 * 0.68 + n2 * 0.46);
    float edge = smoothstep(0.68, 0.98, abs(vEdge));
    float broken = noise(vec2(vUv.y * 62.0 - time * 1.9, vUv.x * 7.0));
    float foam = max(edge * smoothstep(0.48, 0.86, n2), vRapid * smoothstep(0.38, 0.78, broken));
    float downstream = smoothstep(0.44, 0.82, vUv.y) * uAuthorized;
    float depth = 1.0 - smoothstep(0.18, 1.0, abs(vEdge));
    vec3 currentColor = mix(vec3(0.035, 0.18, 0.22), vec3(0.16, 0.48, 0.46), downstream);
    currentColor = mix(currentColor * 0.7, currentColor * 1.28, ripple * 0.42 + (1.0 - depth) * 0.18);
    vec3 color = mix(currentColor, vec3(0.82, 0.91, 0.86), foam);
    float alpha = (0.12 + ripple * 0.1 + streak * 0.045 + foam * 0.46) * uOpacity;
    gl_FragColor = vec4(color, alpha);
  }
`;

function FlowOverlay({
  geometry,
  authorized,
  reducedMotion,
  opacity = 1
}: {
  geometry: BufferGeometry;
  authorized: boolean;
  reducedMotion: boolean;
  opacity?: number;
}) {
  const [normalMapA, normalMapB] = useTexture([
    `${ASSET_ROOT}/water-normal-a.jpg`,
    `${ASSET_ROOT}/water-normal-b.jpg`
  ]);
  useMemo(() => {
    configureTexture(normalMapA, [1, 1]);
    configureTexture(normalMapB, [1, 1]);
  }, [normalMapA, normalMapB]);
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: FLOW_VERTEX,
    fragmentShader: FLOW_FRAGMENT,
    uniforms: {
      uTime: { value: 0 },
      uMotion: { value: reducedMotion ? 0 : 1 },
      uAuthorized: { value: authorized ? 1 : 0 },
      uOpacity: { value: opacity },
      uNormalMapA: { value: normalMapA },
      uNormalMapB: { value: normalMapB }
    },
    transparent: true,
    depthWrite: false
  }), [authorized, normalMapA, normalMapB, opacity, reducedMotion]);
  useEffect(() => () => material.dispose(), [material]);
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = clock.elapsedTime;
    material.uniforms.uAuthorized.value = authorized ? 1 : 0;
    material.uniforms.uMotion.value = reducedMotion ? 0 : 1;
  });
  return <mesh geometry={geometry} material={material} renderOrder={4} />;
}

function RiverSystem({ authorized, reducedMotion }: { authorized: boolean; reducedMotion: boolean }) {
  const mainSamples = useMemo(() => createMainRiverSamples(), []);
  const tributaries = useMemo(() => createTributarySamples(), []);
  const mainGeometry = useMemo(() => createRibbonGeometry(mainSamples, 1, 0.03), [mainSamples]);
  const mainFlowGeometry = useMemo(() => createRibbonGeometry(mainSamples, 0.985, 0.055), [mainSamples]);
  const bankGeometry = useMemo(() => createRibbonGeometry(mainSamples, 1.4, 0.012), [mainSamples]);
  const connectorSamples = useMemo(() => {
    const selected = mainSamples.filter((sample) => sample.z >= -7.5 && sample.z <= 5.2);
    return selected.map((sample, index) => {
      const t = index / Math.max(1, selected.length - 1);
      return {
        ...sample,
        y: sample.y + 0.035 + Math.sin(t * Math.PI) * 0.11,
        width: sample.width * 0.96,
        rapid: Math.max(sample.rapid * 0.72, Math.sin(t * Math.PI * 2) > 0.94 ? 0.24 : 0)
      };
    });
  }, [mainSamples]);
  const connectorGeometry = useMemo(
    () => createRibbonGeometry(connectorSamples, 1, 0),
    [connectorSamples]
  );
  const connectorFlowGeometry = useMemo(
    () => createRibbonGeometry(connectorSamples, 0.98, 0.035),
    [connectorSamples]
  );
  const tributaryGeometries = useMemo(
    () => tributaries.map((samples) => createRibbonGeometry(samples, 1, 0.025)),
    [tributaries]
  );
  const tributaryBankGeometries = useMemo(
    () => tributaries.map((samples) => createRibbonGeometry(samples, 1.58, 0.012)),
    [tributaries]
  );
  const tributaryFlowGeometries = useMemo(
    () => tributaries.map((samples) => createRibbonGeometry(samples, 0.96, 0.047)),
    [tributaries]
  );
  useEffect(() => () => {
    mainGeometry.dispose();
    mainFlowGeometry.dispose();
    connectorGeometry.dispose();
    connectorFlowGeometry.dispose();
    bankGeometry.dispose();
    tributaryGeometries.forEach((geometry) => geometry.dispose());
    tributaryBankGeometries.forEach((geometry) => geometry.dispose());
    tributaryFlowGeometries.forEach((geometry) => geometry.dispose());
  }, [
    bankGeometry,
    connectorFlowGeometry,
    connectorGeometry,
    mainFlowGeometry,
    mainGeometry,
    tributaryBankGeometries,
    tributaryFlowGeometries,
    tributaryGeometries
  ]);

  return (
    <group>
      <mesh geometry={bankGeometry} receiveShadow renderOrder={1}>
        <meshStandardMaterial
          color="#152c27"
          roughness={0.84}
          metalness={0}
          transparent
          opacity={0.9}
          polygonOffset
          polygonOffsetFactor={-1}
        />
      </mesh>
      <mesh geometry={mainGeometry} receiveShadow renderOrder={2} userData={{ dataRef: "flow.main-river" }}>
        <meshPhysicalMaterial
          color={authorized ? "#124c4b" : "#082b34"}
          metalness={0.02}
          roughness={0.21}
          transmission={0.06}
          thickness={0.32}
          clearcoat={0.86}
          clearcoatRoughness={0.22}
          envMapIntensity={0.36}
          side={DoubleSide}
        />
      </mesh>
      <FlowOverlay
        geometry={mainFlowGeometry}
        authorized={authorized}
        reducedMotion={reducedMotion}
      />
      <mesh geometry={connectorGeometry} receiveShadow renderOrder={3}>
        <meshPhysicalMaterial
          color="#092f39"
          roughness={0.22}
          transmission={0.04}
          clearcoat={0.72}
          clearcoatRoughness={0.24}
          envMapIntensity={0.3}
          side={DoubleSide}
        />
      </mesh>
      <FlowOverlay
        geometry={connectorFlowGeometry}
        authorized={authorized}
        reducedMotion={reducedMotion}
      />
      {tributaryBankGeometries.map((geometry, index) => (
        <mesh key={`tributary-bank-${index}`} geometry={geometry} receiveShadow renderOrder={1}>
          <meshStandardMaterial
            color="#152c27"
            roughness={0.76}
            transparent
            opacity={0.9}
            polygonOffset
            polygonOffsetFactor={-1}
          />
        </mesh>
      ))}
      {tributaryGeometries.map((geometry, index) => (
        <mesh key={`tributary-${index}`} geometry={geometry} receiveShadow renderOrder={2}>
          <meshPhysicalMaterial
            color="#0b313a"
            roughness={0.22}
            metalness={0.02}
            transmission={0.04}
            clearcoat={0.7}
            clearcoatRoughness={0.26}
            transparent
            opacity={0.9}
            envMapIntensity={0.3}
            side={DoubleSide}
          />
        </mesh>
      ))}
      {tributaryFlowGeometries.map((geometry, index) => (
        <FlowOverlay
          key={`tributary-flow-${index}`}
          geometry={geometry}
          authorized={false}
          reducedMotion={reducedMotion}
          opacity={0.74}
        />
      ))}
      <Sparkles
        count={reducedMotion ? 0 : 32}
        size={2.2}
        scale={[2.2, 0.9, 2.6]}
        position={[riverCenterX(2.6), riverSurfaceY(2.6) + 0.32, 2.6]}
        speed={0.18}
        noise={0.7}
        color="#d8f1e8"
        opacity={0.34}
      />
    </group>
  );
}

const WATERFALL_VERTEX = `
  varying vec2 vUv;
  uniform float uTime;
  uniform float uMotion;
  void main() {
    vUv = uv;
    vec3 transformed = position;
    transformed.z += sin(uv.y * 34.0 - uTime * 2.2) * 0.018 * uMotion;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`;

const WATERFALL_FRAGMENT = `
  varying vec2 vUv;
  uniform float uTime;
  uniform float uMotion;
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
  }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash21(i), hash21(i + vec2(1., 0.)), f.x),
               mix(hash21(i + vec2(0., 1.)), hash21(i + vec2(1., 1.)), f.x), f.y);
  }
  void main() {
    float time = uTime * uMotion;
    float ribbons = smoothstep(0.54, 0.94, noise(vec2(vUv.x * 13.0, vUv.y * 34.0 + time * 2.7)));
    float edge = smoothstep(0.0, 0.14, vUv.x) * smoothstep(1.0, 0.86, vUv.x);
    float base = 0.32 + ribbons * 0.45;
    vec3 color = mix(vec3(0.19, 0.44, 0.48), vec3(0.86, 0.94, 0.9), ribbons);
    gl_FragColor = vec4(color, base * edge);
  }
`;

function WaterfallSheet({
  z,
  height,
  reducedMotion
}: {
  z: number;
  height: number;
  reducedMotion: boolean;
}) {
  const x = riverCenterX(z);
  const width = riverHalfWidth(z) * 2.04;
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: WATERFALL_VERTEX,
    fragmentShader: WATERFALL_FRAGMENT,
    uniforms: {
      uTime: { value: 0 },
      uMotion: { value: reducedMotion ? 0 : 1 }
    },
    transparent: true,
    depthWrite: false,
    side: DoubleSide
  }), [reducedMotion]);
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = clock.elapsedTime;
    material.uniforms.uMotion.value = reducedMotion ? 0 : 1;
  });
  useEffect(() => () => material.dispose(), [material]);
  const bottom = riverSurfaceY(z) - height * 0.56;
  return (
    <group>
      <mesh
        position={[x, bottom + height * 0.5, z]}
        rotation={[0, -Math.atan2(
          riverCenterX(z + 0.3) - riverCenterX(z - 0.3),
          0.6
        ), 0]}
        scale={[width, height, 1]}
        material={material}
        renderOrder={5}
      >
        <planeGeometry args={[1, 1, 12, 24]} />
      </mesh>
      <Sparkles
        count={reducedMotion ? 0 : 22}
        size={1.8}
        scale={[width * 0.8, 0.3, 0.5]}
        position={[x, bottom + 0.08, z + 0.18]}
        speed={0.14}
        noise={0.72}
        color="#dbece6"
        opacity={0.4}
      />
    </group>
  );
}

type VegetationInstance = {
  position: Vector3;
  scale: number;
  rotation: number;
  color: Color;
  variant: 0 | 1 | 2;
};

function createVegetationInstances() {
  const random = seeded(8207);
  const instances: VegetationInstance[] = [];
  let attempts = 0;
  while (instances.length < 118 && attempts < 1900) {
    attempts += 1;
    const cluster = Math.floor(random() * 8);
    const clusterCenters = [
      [-12, -8], [-10, 3], [-5, -13], [10, -10], [12, 4], [7, 9], [-8, 10], [2, -14]
    ] as const;
    const center = clusterCenters[cluster];
    const x = center[0] + (random() - 0.5) * (4.2 + random() * 4.8);
    const z = center[1] + (random() - 0.5) * (4.2 + random() * 5.6);
    if (Math.abs(x) > BASIN_WIDTH * 0.48 || Math.abs(z) > BASIN_DEPTH * 0.48) continue;
    const distanceToWater = Math.abs(x - riverCenterX(z)) - riverHalfWidth(z);
    const moduleDistance = Math.hypot(x - MODULE_X, z - MODULE_Z);
    if (distanceToWater < 1.15 || moduleDistance < 4.6) continue;
    const y = terrainHeight(x, z);
    if (y > 8.3 || y < 0.5) continue;
    const color = new Color("#607b61").lerp(new Color("#78906d"), random() * 0.6);
    instances.push({
      position: new Vector3(x, y, z),
      scale: 0.62 + random() * 0.74,
      rotation: random() * Math.PI * 2,
      color,
      variant: (instances.length % 3) as 0 | 1 | 2
    });
  }
  return instances;
}

function TreePrimitive({
  node,
  instances,
  scaleFactor,
  reducedMotion
}: {
  node: Mesh<BufferGeometry, MeshStandardMaterial | MeshStandardMaterial[]>;
  instances: VegetationInstance[];
  scaleFactor: number;
  reducedMotion: boolean;
}) {
  const ref = useRef<any>(null);
  const windShaders = useRef<any[]>([]);
  const materials = useMemo(() => {
    const sources = Array.isArray(node.material) ? node.material : [node.material];
    const clones = sources.map((source) => {
      const material = source.clone();
      material.side = DoubleSide;
      material.alphaTest = Math.max(material.alphaTest, 0.32);
      material.transparent = false;
      material.envMapIntensity = 0.52;
      material.roughness = Math.max(material.roughness, 0.72);
      material.onBeforeCompile = (shader: any) => {
        shader.uniforms.uWindTime = { value: 0 };
        shader.uniforms.uWindAmount = { value: reducedMotion ? 0 : 1 };
        shader.vertexShader = shader.vertexShader
          .replace(
            "#include <common>",
            "#include <common>\nuniform float uWindTime;\nuniform float uWindAmount;"
          )
          .replace(
            "#include <begin_vertex>",
            `#include <begin_vertex>
             float windMask = smoothstep(0.08, 1.1, position.y);
             transformed.x += sin(uWindTime * 0.48 + position.y * 3.1 + position.z * 4.4) * 0.012 * windMask * uWindAmount;
             transformed.z += cos(uWindTime * 0.37 + position.y * 2.4 + position.x * 3.8) * 0.008 * windMask * uWindAmount;`
          );
        windShaders.current.push(shader);
      };
      return material;
    });
    return Array.isArray(node.material) ? clones : clones[0];
  }, [node.material, reducedMotion]);
  useEffect(() => {
    const dummy = new Object3D();
    instances.forEach((instance, index) => {
      dummy.position.copy(instance.position);
      dummy.rotation.set(0, instance.rotation, 0);
      dummy.scale.setScalar(instance.scale * scaleFactor);
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
    });
    if (ref.current) {
      ref.current.instanceMatrix.setUsage(DynamicDrawUsage);
      ref.current.instanceMatrix.needsUpdate = true;
    }
  }, [instances, scaleFactor]);

  useFrame(({ clock }) => {
    windShaders.current.forEach((shader) => {
      shader.uniforms.uWindTime.value = clock.elapsedTime;
      shader.uniforms.uWindAmount.value = reducedMotion ? 0 : 1;
    });
  });

  useEffect(() => () => {
    const list = Array.isArray(materials) ? materials : [materials];
    list.forEach((material) => material.dispose());
  }, [materials]);

  return (
    <instancedMesh
      ref={ref}
      args={[node.geometry, materials, instances.length]}
      castShadow
      receiveShadow
      frustumCulled
    />
  );
}

function TreeVariant({
  root,
  instances,
  scaleFactor,
  reducedMotion
}: {
  root: Object3D;
  instances: VegetationInstance[];
  scaleFactor: number;
  reducedMotion: boolean;
}) {
  const meshes = useMemo(() => {
    const next: Mesh<BufferGeometry, MeshStandardMaterial | MeshStandardMaterial[]>[] = [];
    root.traverse((child) => {
      if ((child as Mesh).isMesh) {
        next.push(child as Mesh<BufferGeometry, MeshStandardMaterial | MeshStandardMaterial[]>);
      }
    });
    return next;
  }, [root]);
  return (
    <group>
      {meshes.map((mesh) => (
        <TreePrimitive
          key={mesh.uuid}
          node={mesh}
          instances={instances}
          scaleFactor={scaleFactor}
          reducedMotion={reducedMotion}
        />
      ))}
    </group>
  );
}

function Vegetation({ reducedMotion }: { reducedMotion: boolean }) {
  const model = useGLTF(`${ASSET_ROOT}/fir-sapling-optimized.glb`, false, true) as any;
  const instances = useMemo(() => createVegetationInstances(), []);
  const nodes = [
    model.nodes.fir_sapling_a,
    model.nodes.fir_sapling_b,
    model.nodes.fir_sapling_c
  ] as Object3D[];
  const buckets = useMemo(
    () => ([0, 1, 2] as const).map((variant) => instances.filter((instance) => instance.variant === variant)),
    [instances]
  );
  return (
    <group>
      {nodes.map((node, index) => (
        <TreeVariant
          key={node.uuid}
          root={node}
          instances={buckets[index]}
      scaleFactor={[2.85, 3.75, 4.55][index]}
          reducedMotion={reducedMotion}
        />
      ))}
    </group>
  );
}

useGLTF.preload(`${ASSET_ROOT}/fir-sapling-optimized.glb`, false, true);

function CliffField() {
  const model = useGLTF(`${ASSET_ROOT}/mountainside-optimized.glb`, false, true) as any;
  const node = model.nodes.mountainside as Mesh<BufferGeometry, MeshStandardMaterial>;
  const ref = useRef<any>(null);
  const placements = useMemo(() => [
    { x: -8.2, z: -14.2, scale: 0.49, rotation: 0.32 },
    { x: 8.1, z: -14.1, scale: 0.52, rotation: 2.65 }
  ], []);
  const material = useMemo(() => {
    const next = node.material.clone();
    next.roughness = 0.9;
    next.metalness = 0;
    next.envMapIntensity = 0.58;
    return next;
  }, [node.material]);

  useEffect(() => {
    const dummy = new Object3D();
    placements.forEach((placement, index) => {
      const y = terrainHeight(placement.x, placement.z);
      dummy.position.set(placement.x, y - 4.55 * placement.scale, placement.z);
      dummy.rotation.set(-0.08, placement.rotation, (index % 2 === 0 ? -1 : 1) * 0.08);
      dummy.scale.set(
        placement.scale * (index % 3 === 0 ? 1.16 : 1),
        placement.scale * 0.82,
        placement.scale
      );
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
    });
    if (ref.current) ref.current.instanceMatrix.needsUpdate = true;
  }, [placements]);

  useEffect(() => () => material.dispose(), [material]);

  return (
    <instancedMesh
      ref={ref}
      args={[node.geometry, material, placements.length]}
      castShadow
      receiveShadow
    />
  );
}

useGLTF.preload(`${ASSET_ROOT}/mountainside-optimized.glb`, false, true);

function RockField() {
  const model = useGLTF(`${ASSET_ROOT}/rock-moss-set-optimized.glb`, false, true) as any;
  const node = useMemo(() => {
    let result: Mesh<BufferGeometry, MeshStandardMaterial> | null = null;
    model.scene.traverse((child: Object3D) => {
      if (!result && (child as Mesh).isMesh) {
        result = child as Mesh<BufferGeometry, MeshStandardMaterial>;
      }
    });
    const resolved = result as Mesh<BufferGeometry, MeshStandardMaterial> | null;
    if (!resolved) throw new Error("Rock moss set is missing a mesh");
    return resolved;
  }, [model.scene]);
  const ref = useRef<any>(null);
  const instances = useMemo(() => {
    const random = seeded(42711);
    const placements: { position: Vector3; scale: Vector3; rotation: Euler }[] = [];
    for (let index = 0; index < 36; index += 1) {
      const z = -15 + random() * 30;
      const nearWater = index < 26;
      const side = random() > 0.5 ? 1 : -1;
      const cliffCenters = [
        [-9.5, -7.5], [9.4, -7], [-10.8, 5], [10.6, 5.5]
      ] as const;
      const cliffCenter = cliffCenters[index % cliffCenters.length];
      const x = nearWater
        ? riverCenterX(z) + side * (riverHalfWidth(z) + 0.35 + random() * 1.05)
        : cliffCenter[0] + (random() - 0.5) * 4.6;
      const resolvedZ = nearWater
        ? z
        : cliffCenter[1] + (random() - 0.5) * 4.8;
      if (Math.hypot(x - MODULE_X, resolvedZ - MODULE_Z) < 4.2) continue;
      const y = terrainHeight(x, resolvedZ);
      const scale = nearWater ? 0.25 + random() * 0.17 : 0.3 + random() * 0.2;
      placements.push({
        position: new Vector3(x, y - scale * (nearWater ? 0.08 : 0.2), resolvedZ),
        scale: nearWater
          ? new Vector3(scale * (0.9 + random() * 0.35), scale * (0.72 + random() * 0.28), scale)
          : new Vector3(scale * (1.15 + random() * 0.4), scale * (0.78 + random() * 0.24), scale * 0.88),
        rotation: new Euler((random() - 0.5) * 0.16, random() * Math.PI * 2, (random() - 0.5) * 0.18)
      });
    }
    return placements;
  }, []);
  const material = useMemo(() => {
    const next = node.material.clone();
    next.roughness = 0.88;
    next.metalness = 0;
    next.envMapIntensity = 0.62;
    next.color.set("#6d7468");
    return next;
  }, [node.material]);
  useEffect(() => {
    const dummy = new Object3D();
    instances.forEach((instance, index) => {
      dummy.position.copy(instance.position);
      dummy.rotation.copy(instance.rotation);
      dummy.scale.copy(instance.scale);
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
    });
    if (ref.current) ref.current.instanceMatrix.needsUpdate = true;
  }, [instances]);
  useEffect(() => () => material.dispose(), [material]);
  return (
    <instancedMesh
      ref={ref}
      args={[node.geometry, material, instances.length]}
      castShadow
      receiveShadow
    />
  );
}

useGLTF.preload(`${ASSET_ROOT}/rock-moss-set-optimized.glb`, false, true);

function BoulderField() {
  const model = useGLTF(`${ASSET_ROOT}/boulder-optimized.glb`, false, true) as any;
  const node = useMemo(() => {
    let result: Mesh<BufferGeometry, MeshStandardMaterial> | null = null;
    model.scene.traverse((child: Object3D) => {
      if (!result && (child as Mesh).isMesh) {
        result = child as Mesh<BufferGeometry, MeshStandardMaterial>;
      }
    });
    const resolved = result as Mesh<BufferGeometry, MeshStandardMaterial> | null;
    if (!resolved) throw new Error("Boulder asset is missing a mesh");
    return resolved;
  }, [model.scene]);
  const ref = useRef<any>(null);
  const placements = useMemo(() => {
    const random = seeded(97031);
    const result: { position: Vector3; scale: Vector3; rotation: Euler }[] = [];
    let attempts = 0;
    while (result.length < 16 && attempts < 120) {
      attempts += 1;
      const z = -12.5 + random() * 25;
      const side = random() > 0.5 ? 1 : -1;
      const scale = 0.56 + random() * 0.46;
      const x = riverCenterX(z) + side * (riverHalfWidth(z) + 0.55 + random() * 1.55);
      if (Math.hypot(x - MODULE_X, z - MODULE_Z) < 4.25) continue;
      result.push({
        position: new Vector3(x, terrainHeight(x, z) - 0.18, z),
        scale: new Vector3(
          scale * (0.86 + random() * 0.38),
          scale * (0.72 + random() * 0.34),
          scale * (0.82 + random() * 0.4)
        ),
        rotation: new Euler((random() - 0.5) * 0.2, random() * Math.PI * 2, (random() - 0.5) * 0.16)
      });
    }
    return result;
  }, []);
  const material = useMemo(() => {
    const next = node.material.clone();
    next.color.set("#74776e");
    next.roughness = 0.98;
    next.metalness = 0;
    next.envMapIntensity = 0.5;
    return next;
  }, [node.material]);
  useEffect(() => {
    const dummy = new Object3D();
    placements.forEach((placement, index) => {
      dummy.position.copy(placement.position);
      dummy.rotation.copy(placement.rotation);
      dummy.scale.copy(placement.scale);
      dummy.updateMatrix();
      ref.current?.setMatrixAt(index, dummy.matrix);
    });
    if (ref.current) ref.current.instanceMatrix.needsUpdate = true;
  }, [placements]);
  useEffect(() => () => material.dispose(), [material]);
  return (
    <instancedMesh
      ref={ref}
      args={[node.geometry, material, placements.length]}
      castShadow
      receiveShadow
    />
  );
}

useGLTF.preload(`${ASSET_ROOT}/boulder-optimized.glb`, false, true);

function ArchitectureModule({
  mode,
  receiptVisible,
  consoleContent,
  onEnter,
  onExit
}: {
  mode: BeautyViewMode;
  receiptVisible: boolean;
  consoleContent: ReactNode;
  onEnter: () => void;
  onExit: () => void;
}) {
  const [woodMap, woodNormal, rockMap, rockNormal] = useTexture([
    `${ASSET_ROOT}/wood-diff.webp`,
    `${ASSET_ROOT}/wood-normal.webp`,
    `${ASSET_ROOT}/rock-diff.webp`,
    `${ASSET_ROOT}/rock-normal.webp`
  ]);
  useMemo(() => {
    configureTexture(woodMap, [2.2, 2.2], true);
    configureTexture(woodNormal, [2.2, 2.2]);
    configureTexture(rockMap, [2.4, 2.4], true);
    configureTexture(rockNormal, [2.4, 2.4]);
  }, [rockMap, rockNormal, woodMap, woodNormal]);
  const moduleModel = useGLTF(`${ASSET_ROOT}/hydrology-house.glb`, false, true) as any;
  const moduleShell = useMemo(() => {
    const clone = moduleModel.scene.clone(true);
    clone.traverse((child: Object3D) => {
      const mesh = child as Mesh<BufferGeometry, MeshStandardMaterial>;
      if (!mesh.isMesh) return;
      const source = mesh.material;
      const material = source.clone();
      if (material.name === "StoneShell") {
        material.map = rockMap;
        material.normalMap = rockNormal;
        material.color.set("#77776f");
      } else if (material.name === "TimberFrame" || material.name === "WeatheredRoof") {
        material.map = woodMap;
        material.normalMap = woodNormal;
        material.color.set(material.name === "WeatheredRoof" ? "#695648" : "#574333");
      } else {
        material.color.set("#252b28");
        material.roughness = 0.72;
      }
      material.envMapIntensity = material.name === "DarkMetal" ? 0.68 : 0.46;
      material.needsUpdate = true;
      mesh.material = material;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
    });
    return clone;
  }, [moduleModel.scene, rockMap, rockNormal, woodMap, woodNormal]);
  useEffect(() => () => {
    moduleShell.traverse((child: Object3D) => {
      const mesh = child as Mesh<BufferGeometry, MeshStandardMaterial>;
      if (mesh.isMesh) mesh.material.dispose();
    });
  }, [moduleShell]);

  const inside = mode === "interior";
  return (
    <group
      position={[MODULE_X, MODULE_Y, MODULE_Z]}
      userData={{ dataRef: "module.hydrology@1" }}
    >
      <primitive object={moduleShell} />
      <mesh position={[0, 1.45, -1.74]} scale={[3.25, 2.2, 0.07]}>
        <boxGeometry />
        <meshPhysicalMaterial
          color="#6f8e8e"
          roughness={0.12}
          metalness={0.02}
          transmission={0.48}
          thickness={0.14}
          transparent
          opacity={0.52}
          envMapIntensity={1.2}
        />
      </mesh>

      <mesh
        position={[0, 1.25, 1.78]}
        scale={[1.28, 2.45, 0.12]}
        onClick={(event) => {
          event.stopPropagation();
          onEnter();
        }}
      >
        <boxGeometry />
        <meshPhysicalMaterial
          color="#6f8d8d"
          transmission={0.7}
          thickness={0.08}
          roughness={0.08}
          transparent
          opacity={inside ? 0.04 : 0.09}
          envMapIntensity={1.5}
        />
      </mesh>

      <mesh position={[0, 0.71, -0.7]} scale={[1.95, 0.06, 1.05]}>
        <boxGeometry />
        <meshStandardMaterial
          color={receiptVisible ? "#f5b24f" : "#1f5c61"}
          emissive={receiptVisible ? "#ee8c25" : "#163f42"}
          emissiveIntensity={receiptVisible ? 2.2 : 0.55}
          roughness={0.26}
        />
      </mesh>

      <pointLight
        position={[0, 2.35, 0.3]}
        intensity={inside ? 28 : 16}
        distance={8}
        decay={2}
        color="#ffb45f"
        castShadow={false}
      />
      <pointLight
        position={[0, 1.4, -1.3]}
        intensity={inside ? 13 : 7}
        distance={5}
        decay={2}
        color="#76c7c2"
      />

      {!inside && (
      <Html position={[0.25, 2.4, 2.12]} center distanceFactor={14} zIndexRange={[12, 8]}>
          <button className="beautyWorldCallout beautyWorldCallout--module" type="button" onClick={onEnter}>
            <span>módulo entrável</span>
            <strong>Casa da Hidrografia</strong>
            <small>entrar · mesma seleção</small>
          </button>
        </Html>
      )}

      {inside && (
        <>
          <Html
            transform
            position={[0, 1.48, -1.61]}
            distanceFactor={1.18}
            zIndexRange={[20, 14]}
          >
            <div className="beautyConsoleProjection">
              <div className="beautyConsoleFrame">
                <span className="beautyConsoleHardware">HYDROGRAPHY / BASIN 01</span>
                {consoleContent}
              </div>
            </div>
          </Html>
          <Html position={[-1.65, 2.45, 1.2]} center distanceFactor={5.4} zIndexRange={[24, 20]}>
            <button className="beautyInteriorExit" type="button" onClick={onExit}>
              ← voltar à bacia
            </button>
          </Html>
        </>
      )}
    </group>
  );
}

const MIST_VERTEX = `
  varying vec2 vUv;
  uniform float uTime;
  uniform float uMotion;
  void main() {
    vUv = uv;
    vec3 transformed = position;
    transformed.x += sin(uTime * 0.08 + position.z * 0.3) * 0.7 * uMotion;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`;
const MIST_FRAGMENT = `
  varying vec2 vUv;
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
  }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash21(i), hash21(i + vec2(1., 0.)), f.x),
               mix(hash21(i + vec2(0., 1.)), hash21(i + vec2(1., 1.)), f.x), f.y);
  }
  void main() {
    float radial = smoothstep(0.55, 0.05, abs(vUv.y - 0.5));
    float edge = smoothstep(0.0, 0.24, vUv.x) * smoothstep(1.0, 0.76, vUv.x);
    float n = noise(vUv * vec2(5.0, 2.0));
    gl_FragColor = vec4(vec3(0.58, 0.7, 0.67), radial * edge * (0.08 + n * 0.07));
  }
`;

function ValleyMist({ reducedMotion }: { reducedMotion: boolean }) {
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: MIST_VERTEX,
    fragmentShader: MIST_FRAGMENT,
    uniforms: {
      uTime: { value: 0 },
      uMotion: { value: reducedMotion ? 0 : 1 }
    },
    transparent: true,
    depthWrite: false,
    side: DoubleSide
  }), [reducedMotion]);
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = clock.elapsedTime;
  });
  useEffect(() => () => material.dispose(), [material]);
  return (
    <group>
      <mesh position={[0, 2.9, -10]} rotation={[-Math.PI / 2, 0, 0]} scale={[17, 6, 1]} material={material}>
        <planeGeometry />
      </mesh>
      <mesh position={[-2, 1.85, 7]} rotation={[-Math.PI / 2, 0, 0.12]} scale={[12, 4, 1]} material={material}>
        <planeGeometry />
      </mesh>
    </group>
  );
}

function SourceCallout({ onSelect }: { onSelect: () => void }) {
  const z = -12.8;
  const x = riverCenterX(z);
  const y = riverSurfaceY(z) + 0.45;
  return (
    <group position={[x, y, z]}>
      <mesh position={[0, -0.25, 0]}>
        <sphereGeometry args={[0.09, 16, 12]} />
        <meshStandardMaterial color="#f4b057" emissive="#e6802a" emissiveIntensity={2.3} />
      </mesh>
      <pointLight color="#f2a552" intensity={4} distance={2.4} decay={2} />
      <Html position={[0.2, 0.25, 0]} center distanceFactor={19} zIndexRange={[10, 7]}>
        <button className="beautyWorldCallout" type="button" onClick={onSelect}>
          <span>evidência observada</span>
          <strong>Nascente da Clareza</strong>
          <small>proveniência 0,67 · inspecionar</small>
        </button>
      </Html>
    </group>
  );
}

function ReceiptGate({ visible }: { visible: boolean }) {
  if (!visible) return null;
  const z = 6.2;
  const x = riverCenterX(z);
  return (
    <group position={[x, riverSurfaceY(z) + 0.16, z]}>
      <mesh rotation={[0, 0, Math.PI / 2]} castShadow>
        <torusGeometry args={[0.43, 0.055, 12, 42]} />
        <meshStandardMaterial
          color="#f4ad4b"
          emissive="#ef7e19"
          emissiveIntensity={2.8}
          roughness={0.34}
        />
      </mesh>
      <pointLight color="#f6a23d" intensity={8} distance={4.2} decay={2} />
    </group>
  );
}

function RendererMetrics({
  onMetrics
}: {
  onMetrics: (metrics: BeautyMetrics) => void;
}) {
  const { gl, scene } = useThree();
  const startedAt = useRef(performance.now());
  const firstFrame = useRef(0);
  const accumulator = useRef({ seconds: 0, frames: 0, last: 0 });
  useEffect(() => addAfterEffect(() => {
    if (!firstFrame.current) firstFrame.current = performance.now() - startedAt.current;
  }), []);
  useFrame((_, delta) => {
    accumulator.current.seconds += delta;
    accumulator.current.frames += 1;
    if (accumulator.current.seconds < 1) return;
    const fps = accumulator.current.frames / accumulator.current.seconds;
    const frameMs = 1000 / Math.max(fps, 1);
    let calls = 6;
    let triangles = 0;
    scene.traverse((object) => {
      const mesh = object as Mesh;
      if (!mesh.isMesh || !mesh.visible || !mesh.geometry) return;
      const geometry = mesh.geometry as BufferGeometry;
      const baseTriangles = geometry.index
        ? geometry.index.count / 3
        : geometry.attributes.position
          ? geometry.attributes.position.count / 3
          : 0;
      const instanceCount = "count" in mesh && typeof mesh.count === "number" ? mesh.count : 1;
      triangles += baseTriangles * instanceCount;
      const materialCount = Array.isArray(mesh.material) ? mesh.material.length : 1;
      calls += Math.max(1, geometry.groups.length || materialCount);
    });
    const metrics: BeautyMetrics = {
      fps: Math.round(fps),
      frameMs: Number(frameMs.toFixed(1)),
      calls,
      triangles: Math.round(triangles),
      geometries: gl.info.memory.geometries,
      textures: gl.info.memory.textures,
      firstFrameMs: Math.round(firstFrame.current)
    };
    const now = performance.now();
    if (now - accumulator.current.last > 850) {
      accumulator.current.last = now;
      onMetrics(metrics);
      (window as Window & { __ANATTA_BEAUTY_METRICS__?: BeautyMetrics })
        .__ANATTA_BEAUTY_METRICS__ = metrics;
    }
    accumulator.current.seconds = 0;
    accumulator.current.frames = 0;
  });
  return null;
}

export function BasinScene({
  viewMode,
  authorized,
  receiptVisible,
  reducedMotion,
  consoleContent,
  onEnter,
  onExit,
  onSelectTension,
  onMetrics,
  onInteriorReached
}: BasinSceneProps) {
  return (
    <>
      <color attach="background" args={["#44514d"]} />
      <fogExp2 attach="fog" args={["#4a5853", 0.008]} />
      <PerspectiveCamera makeDefault position={HERO_POSITION} fov={40} near={0.08} far={110} />
      <CameraDirector
        mode={viewMode}
        reducedMotion={reducedMotion}
        onInteriorReached={onInteriorReached}
      />

      <Environment files={ENVIRONMENT_MAP} />
      <ambientLight intensity={0.06} color="#91aaa5" />
      <hemisphereLight args={["#9db7b4", "#1d2721", 0.34]} />
      <directionalLight
        position={[-12, 15, 5]}
        intensity={3.45}
        color="#ffd3a3"
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={0.5}
        shadow-camera-far={55}
        shadow-camera-left={-19}
        shadow-camera-right={19}
        shadow-camera-top={18}
        shadow-camera-bottom={-18}
        shadow-bias={-0.00018}
        shadow-normalBias={0.035}
      />

      <Terrain />
      <RiverSystem authorized={authorized} reducedMotion={reducedMotion} />
      <WaterfallSheet z={2.75} height={1.22} reducedMotion={reducedMotion} />
      <WaterfallSheet z={-7.1} height={0.86} reducedMotion={reducedMotion} />
      <CliffField />
      <RockField />
      <BoulderField />
      <Vegetation reducedMotion={reducedMotion} />
      <ArchitectureModule
        mode={viewMode}
        receiptVisible={receiptVisible}
        consoleContent={consoleContent}
        onEnter={onEnter}
        onExit={onExit}
      />
      {viewMode === "exterior" && <SourceCallout onSelect={onSelectTension} />}
      <ReceiptGate visible={receiptVisible} />
      <ValleyMist reducedMotion={reducedMotion} />
      <ContactShadows
        position={[MODULE_X, MODULE_Y + 0.03, MODULE_Z]}
        opacity={0.42}
        scale={8}
        blur={2.6}
        far={7}
        resolution={256}
        frames={reducedMotion ? 1 : 24}
      />

      <EffectComposer multisampling={2} enableNormalPass>
        <SSAO
          samples={8}
          radius={0.13}
          intensity={16}
          luminanceInfluence={0.72}
          worldDistanceThreshold={20}
          worldDistanceFalloff={5}
          worldProximityThreshold={0.42}
          worldProximityFalloff={0.12}
        />
        <Bloom
          intensity={0.18}
          luminanceThreshold={1.12}
          luminanceSmoothing={0.28}
          mipmapBlur
        />
        <HueSaturation saturation={0.085} hue={0.002} />
        <Vignette offset={0.16} darkness={0.42} eskil={false} />
      </EffectComposer>
      <RendererMetrics onMetrics={onMetrics} />
    </>
  );
}
