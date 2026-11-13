import { SphereGeometry, Vector3 } from "three";

export const SAND_PLANET_RADIUS = 6;

export function sandPlanetDisplacement(x: number, y: number, z: number) {
  const length = Math.hypot(x, y, z) || 1;
  const nx = x / length;
  const ny = y / length;
  const nz = z / length;
  const continental = Math.sin(nx * 4.7 + nz * 2.2) * 0.38
    + Math.cos(ny * 5.3 - nx * 1.7) * 0.24;
  const duneBands = Math.abs(Math.sin((nx + nz * 0.34) * 17 + ny * 3.2)) * 0.13;
  const oldBasin = Math.exp(-((nx - 0.62) ** 2) / 0.11 - ((ny - 0.28) ** 2) / 0.08) * -0.46;
  const dryRill = Math.exp(-((nx - Math.sin(ny * 5.4) * 0.18 - 0.12) ** 2) / 0.014) * -0.16;
  return continental + duneBands + oldBasin + dryRill;
}

export function createSandPlanetGeometry(widthSegments = 192, heightSegments = 128) {
  const geometry = new SphereGeometry(SAND_PLANET_RADIUS, widthSegments, heightSegments);
  const position = geometry.attributes.position;
  const direction = new Vector3();

  for (let index = 0; index < position.count; index += 1) {
    direction.fromBufferAttribute(position, index).normalize();
    const displacement = sandPlanetDisplacement(direction.x, direction.y, direction.z);
    direction.multiplyScalar(SAND_PLANET_RADIUS + displacement);
    position.setXYZ(index, direction.x, direction.y, direction.z);
  }

  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

export function applySandBrush(
  geometry: SphereGeometry,
  center: Vector3,
  strength = 0.075,
  angularRadius = 0.22
) {
  const position = geometry.attributes.position;
  const centerNormal = center.clone().normalize();
  const vertex = new Vector3();
  let changed = false;

  for (let index = 0; index < position.count; index += 1) {
    vertex.fromBufferAttribute(position, index);
    const radius = vertex.length();
    const angle = Math.acos(Math.min(1, Math.max(-1, vertex.clone().normalize().dot(centerNormal))));
    if (angle > angularRadius) continue;
    const falloff = Math.exp(-(angle * angle) / Math.max(0.0001, angularRadius * angularRadius * 0.34));
    vertex.normalize().multiplyScalar(radius + strength * falloff);
    position.setXYZ(index, vertex.x, vertex.y, vertex.z);
    changed = true;
  }

  if (changed) {
    position.needsUpdate = true;
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
  }
  return changed;
}
