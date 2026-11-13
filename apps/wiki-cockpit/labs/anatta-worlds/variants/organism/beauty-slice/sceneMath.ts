import {
  BufferAttribute,
  BufferGeometry,
  Color,
  PlaneGeometry,
  Vector3
} from "three";

export type RiverSample = {
  x: number;
  y: number;
  z: number;
  width: number;
  rapid: number;
};

export const BASIN_WIDTH = 38;
export const BASIN_DEPTH = 34;

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));
const smoothstep = (edge0: number, edge1: number, value: number) => {
  const t = clamp01((value - edge0) / (edge1 - edge0));
  return t * t * (3 - 2 * t);
};

function hash2(x: number, z: number) {
  const value = Math.sin(x * 127.1 + z * 311.7) * 43758.5453123;
  return value - Math.floor(value);
}

function valueNoise(x: number, z: number) {
  const ix = Math.floor(x);
  const iz = Math.floor(z);
  const fx = x - ix;
  const fz = z - iz;
  const ux = fx * fx * (3 - 2 * fx);
  const uz = fz * fz * (3 - 2 * fz);
  const a = hash2(ix, iz);
  const b = hash2(ix + 1, iz);
  const c = hash2(ix, iz + 1);
  const d = hash2(ix + 1, iz + 1);
  const top = a + (b - a) * ux;
  const bottom = c + (d - c) * ux;
  return top + (bottom - top) * uz;
}

function fbm(x: number, z: number) {
  let value = 0;
  let amplitude = 0.5;
  let frequency = 1;
  for (let octave = 0; octave < 5; octave += 1) {
    value += (valueNoise(x * frequency, z * frequency) - 0.5) * 2 * amplitude;
    frequency *= 2.03;
    amplitude *= 0.48;
  }
  return value;
}

export function riverCenterX(z: number) {
  return -0.35
    + Math.sin(z * 0.245) * 1.08
    + Math.sin(z * 0.57 + 0.8) * 0.38;
}

export function riverSurfaceY(z: number) {
  const normalized = clamp01((-z + BASIN_DEPTH * 0.5) / BASIN_DEPTH);
  const upperShelf = 0.34 * (1 - smoothstep(-8.2, -5.8, z));
  const middleShelf = 0.2 * (1 - smoothstep(1.2, 4.1, z));
  return 0.42 + normalized * 1.2 + upperShelf + middleShelf;
}

export function riverHalfWidth(z: number) {
  const normalized = clamp01((z + BASIN_DEPTH * 0.5) / BASIN_DEPTH);
  return 0.62 + normalized * 0.82 + Math.sin(z * 0.4) * 0.08;
}

function gaussian(
  x: number,
  z: number,
  centerX: number,
  centerZ: number,
  radiusX: number,
  radiusZ: number,
  amplitude: number
) {
  const dx = (x - centerX) / radiusX;
  const dz = (z - centerZ) / radiusZ;
  return Math.exp(-(dx * dx + dz * dz)) * amplitude;
}

function distanceToSegment(
  x: number,
  z: number,
  ax: number,
  az: number,
  bx: number,
  bz: number
) {
  const abx = bx - ax;
  const abz = bz - az;
  const denominator = abx * abx + abz * abz;
  const t = denominator === 0
    ? 0
    : clamp01(((x - ax) * abx + (z - az) * abz) / denominator);
  const px = ax + abx * t;
  const pz = az + abz * t;
  return Math.hypot(x - px, z - pz);
}

const LEFT_TRIBUTARY: readonly [number, number][] = [
  [-12.8, -14.8],
  [-11.9, -12.6],
  [-10.2, -11.1],
  [-9.5, -9.1],
  [-7.8, -7.6],
  [-6.6, -5.8],
  [-4.7, -4.5],
  [riverCenterX(-3.8), -3.8]
];

const RIGHT_TRIBUTARY: readonly [number, number][] = [
  [13.6, -14.4],
  [12.4, -12.8],
  [10.7, -11.4],
  [10.1, -9.7],
  [8.2, -8.6],
  [6.6, -7.1],
  [4.5, -6.2],
  [riverCenterX(-5.7), -5.7]
];

function tributaryDistance(x: number, z: number, points: readonly [number, number][]) {
  let distance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    distance = Math.min(
      distance,
      distanceToSegment(x, z, current[0], current[1], next[0], next[1])
    );
  }
  return distance;
}

export function terrainHeight(x: number, z: number) {
  const backRise = clamp01((-z + 10) / 28) * 1.15;
  const broadNoise = fbm(x * 0.075, z * 0.075) * 1.18;
  const detailNoise = fbm(x * 0.22 + 13.2, z * 0.22 - 7.4) * 0.62;
  const fracturedDetail = fbm(x * 0.48 - 5.6, z * 0.48 + 11.2) * 0.22;
  const ridgeSignal = fbm(x * 0.16 - 8.3, z * 0.16 + 4.7);
  const brokenRidges = Math.pow(1 - Math.abs(ridgeSignal), 4) * 1.16;
  const leftMass =
    gaussian(x, z, -12.5, -8, 7.2, 9.8, 5.7)
    + gaussian(x, z, -11.8, 7.5, 6.8, 8, 3.6);
  const rightMass =
    gaussian(x, z, 12.8, -10.5, 7.4, 8.6, 6.5)
    + gaussian(x, z, 12.4, 5.8, 7.8, 7.6, 3.9);
  const backgroundPeak =
    gaussian(x, z, -2.5, -15.8, 9.6, 4.6, 3.8)
    + gaussian(x, z, 7.5, -15.7, 6.5, 4.2, 3.2);
  const crags =
    gaussian(x, z, -8.6, -2.4, 3.6, 5.8, 1.8)
    + gaussian(x, z, 8.8, -4.7, 4.1, 5.4, 2.1)
    + gaussian(x, z, -11.4, 8.2, 3.8, 4.5, 1.35);
  let height =
    0.62
    + backRise
    + broadNoise
    + detailNoise
    + fracturedDetail
    + brokenRidges
    + leftMass
    + rightMass
    + backgroundPeak
    + crags;

  const mainDistance = Math.abs(x - riverCenterX(z));
  const riverBlend = smoothstep(3.9, 0.1, mainDistance);
  const mainBed = riverSurfaceY(z) - 0.34 + Math.min(mainDistance, 2.7) * 0.46;
  height += (mainBed - height) * riverBlend;

  const leftDistance = tributaryDistance(x, z, LEFT_TRIBUTARY);
  const rightDistance = tributaryDistance(x, z, RIGHT_TRIBUTARY);
  const tributary = Math.min(leftDistance, rightDistance);
  if (tributary < 2.2 && z < -3.2) {
    const tributaryBlend = smoothstep(2.2, 0.08, tributary) * 0.88;
    const tributaryBed = riverSurfaceY(z) + 0.2 + Math.min(tributary, 1.6) * 0.3;
    height += (tributaryBed - height) * tributaryBlend;
  }

  const edgeLift = smoothstep(13, 19, Math.abs(x)) * 2.2;
  return height + edgeLift;
}

export function createTerrainGeometry() {
  const geometry = new PlaneGeometry(BASIN_WIDTH, BASIN_DEPTH, 176, 156);
  geometry.rotateX(-Math.PI / 2);
  const position = geometry.attributes.position as BufferAttribute;
  for (let index = 0; index < position.count; index += 1) {
    const x = position.getX(index);
    const z = position.getZ(index);
    position.setY(index, terrainHeight(x, z));
  }
  position.needsUpdate = true;
  geometry.computeVertexNormals();

  const normal = geometry.attributes.normal as BufferAttribute;
  const colors = new Float32Array(position.count * 3);
  const grass = new Color("#536347");
  const moss = new Color("#435b49");
  const rock = new Color("#807d70");
  const high = new Color("#696c62");
  const tint = new Color();
  for (let index = 0; index < position.count; index += 1) {
    const y = position.getY(index);
    const slope = 1 - Math.max(0, normal.getY(index));
    const x = position.getX(index);
    const z = position.getZ(index);
    const moisture = 1 - clamp01((Math.abs(x - riverCenterX(z)) - riverHalfWidth(z)) / 4);
    tint.copy(grass).lerp(moss, moisture * 0.42);
    tint.lerp(rock, smoothstep(0.1, 0.46, slope));
    tint.lerp(high, smoothstep(4.4, 6.8, y) * 0.44);
    const macro = 0.9 + valueNoise(x * 0.11, z * 0.11) * 0.18;
    colors[index * 3] = tint.r * macro;
    colors[index * 3 + 1] = tint.g * macro;
    colors[index * 3 + 2] = tint.b * macro;
  }
  geometry.setAttribute("color", new BufferAttribute(colors, 3));
  geometry.computeBoundingSphere();
  return geometry;
}

export function createMainRiverSamples(count = 132): RiverSample[] {
  return Array.from({ length: count }, (_, index) => {
    const t = index / (count - 1);
    const z = -BASIN_DEPTH * 0.5 + t * BASIN_DEPTH;
    const rapid = clamp01(
      gaussian(0, z, 0, -7, 1, 2.1, 1)
      + gaussian(0, z, 0, 2.6, 1, 1.8, 0.9)
      + gaussian(0, z, 0, 9.2, 1, 1.5, 0.65)
    );
    return {
      x: riverCenterX(z),
      y: riverSurfaceY(z),
      z,
      width: riverHalfWidth(z) * 2,
      rapid
    };
  });
}

function samplePolyline(
  points: readonly [number, number][],
  count: number,
  startWidth: number,
  endWidth: number
) {
  const cumulative = [0];
  for (let index = 1; index < points.length; index += 1) {
    cumulative.push(
      cumulative[index - 1]
      + Math.hypot(points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
    );
  }
  const total = cumulative[cumulative.length - 1];
  return Array.from({ length: count }, (_, sampleIndex): RiverSample => {
    const distance = total * (sampleIndex / (count - 1));
    let segment = 0;
    while (segment < cumulative.length - 2 && cumulative[segment + 1] < distance) segment += 1;
    const segmentLength = cumulative[segment + 1] - cumulative[segment];
    const local = segmentLength === 0 ? 0 : (distance - cumulative[segment]) / segmentLength;
    const x = points[segment][0] + (points[segment + 1][0] - points[segment][0]) * local;
    const z = points[segment][1] + (points[segment + 1][1] - points[segment][1]) * local;
    const t = sampleIndex / (count - 1);
    return {
      x,
      z,
      y: terrainHeight(x, z) + 0.09,
      width: startWidth + (endWidth - startWidth) * t,
      rapid: smoothstep(0.1, 0.7, Math.sin(t * Math.PI * 3.2) * 0.5 + 0.5) * 0.48
    };
  });
}

export function createTributarySamples() {
  return [
    samplePolyline(LEFT_TRIBUTARY, 54, 0.34, 0.92),
    samplePolyline(RIGHT_TRIBUTARY, 54, 0.38, 0.98)
  ];
}

export function createRibbonGeometry(samples: RiverSample[], widthScale = 1, yOffset = 0) {
  const positions: number[] = [];
  const uvs: number[] = [];
  const edges: number[] = [];
  const rapids: number[] = [];
  const indices: number[] = [];

  samples.forEach((sample, index) => {
    const previous = samples[Math.max(0, index - 1)];
    const next = samples[Math.min(samples.length - 1, index + 1)];
    const tangent = new Vector3(next.x - previous.x, 0, next.z - previous.z).normalize();
    const sideX = -tangent.z;
    const sideZ = tangent.x;
    const half = sample.width * 0.5 * widthScale;
    for (const edge of [-1, 1] as const) {
      positions.push(
        sample.x + sideX * half * edge,
        sample.y + yOffset,
        sample.z + sideZ * half * edge
      );
      uvs.push(edge === -1 ? 0 : 1, index / (samples.length - 1));
      edges.push(edge);
      rapids.push(sample.rapid);
    }
    if (index < samples.length - 1) {
      const offset = index * 2;
      indices.push(offset, offset + 1, offset + 2, offset + 1, offset + 3, offset + 2);
    }
  });

  const geometry = new BufferGeometry();
  geometry.setIndex(indices);
  geometry.setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  geometry.setAttribute("uv", new BufferAttribute(new Float32Array(uvs), 2));
  geometry.setAttribute("aEdge", new BufferAttribute(new Float32Array(edges), 1));
  geometry.setAttribute("aRapid", new BufferAttribute(new Float32Array(rapids), 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

export function seeded(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}
