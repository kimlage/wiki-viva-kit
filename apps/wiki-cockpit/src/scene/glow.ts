import * as THREE from "three";

// Canvas-generated soft radial textures shared by every glow sprite and point
// cloud in the scene. One white texture, tinted per-material, keeps GPU memory
// flat regardless of how many glowing elements exist.

let glowTextureCache: THREE.CanvasTexture | null = null;
let dotTextureCache: THREE.CanvasTexture | null = null;

function radialTexture(size: number, stops: [number, string][]): THREE.CanvasTexture | null {
  if (typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  if (!context) return null;
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [offset, color] of stops) gradient.addColorStop(offset, color);
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

export function glowTexture(): THREE.CanvasTexture | null {
  if (!glowTextureCache) {
    glowTextureCache = radialTexture(128, [
      [0, "rgba(255,255,255,1)"],
      [0.25, "rgba(255,255,255,0.55)"],
      [0.55, "rgba(255,255,255,0.16)"],
      [1, "rgba(255,255,255,0)"]
    ]);
  }
  return glowTextureCache;
}

export function dotTexture(): THREE.CanvasTexture | null {
  if (!dotTextureCache) {
    dotTextureCache = radialTexture(64, [
      [0, "rgba(255,255,255,1)"],
      [0.5, "rgba(255,255,255,0.85)"],
      [0.85, "rgba(255,255,255,0.12)"],
      [1, "rgba(255,255,255,0)"]
    ]);
  }
  return dotTextureCache;
}

const ringTextureCache = new Map<number, THREE.CanvasTexture | null>();

export function ringTexture(strokeRatio = 0.07): THREE.CanvasTexture | null {
  const key = Math.round(strokeRatio * 1000);
  if (!ringTextureCache.has(key)) {
    if (typeof document === "undefined") {
      ringTextureCache.set(key, null);
    } else {
      const size = 128;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d");
      if (!context) {
        ringTextureCache.set(key, null);
      } else {
        const stroke = size * strokeRatio;
        context.strokeStyle = "rgba(255,255,255,1)";
        context.lineWidth = stroke;
        context.shadowColor = "rgba(255,255,255,0.8)";
        context.shadowBlur = stroke * 1.2;
        context.beginPath();
        context.arc(size / 2, size / 2, size / 2 - stroke * 1.8, 0, Math.PI * 2);
        context.stroke();
        const texture = new THREE.CanvasTexture(canvas);
        texture.needsUpdate = true;
        ringTextureCache.set(key, texture);
      }
    }
  }
  return ringTextureCache.get(key) ?? null;
}
