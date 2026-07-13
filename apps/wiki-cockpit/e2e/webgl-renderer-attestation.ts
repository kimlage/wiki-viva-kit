import type { Page } from "@playwright/test";

export const WEBGL_RENDERER_ATTESTATION_SCHEMA = "wiki_webgl_renderer_attestation.v1" as const;

export type WebglRendererAttestation = {
  schema_version: typeof WEBGL_RENDERER_ATTESTATION_SCHEMA;
  requested_gpu: true;
  classification: "hardware" | "software" | "unknown";
  blocker: string | null;
  context: {
    drawing_buffer_width: number;
    drawing_buffer_height: number;
    lost: boolean;
    version: string;
    shading_language_version: string;
  } | null;
  renderer: {
    masked_vendor: string;
    masked_renderer: string;
    unmasked_vendor: string;
    unmasked_renderer: string;
    debug_renderer_info: boolean;
  } | null;
};

const SOFTWARE_RENDERER = /swiftshader|llvmpipe|softpipe|software|lavapipe|mesa offscreen|microsoft basic render/i;

export function webglRendererAttestationBlocker(
  attestation: WebglRendererAttestation
): string | null {
  if (!attestation.context || !attestation.renderer) return "webgl_context_unavailable";
  if (attestation.context.lost) return "webgl_context_lost";
  if (
    !attestation.context.version.trim() ||
    !attestation.context.shading_language_version.trim()
  ) {
    return "webgl_context_identity_missing";
  }
  if (
    attestation.context.drawing_buffer_width <= 0 ||
    attestation.context.drawing_buffer_height <= 0
  ) {
    return "webgl_drawing_buffer_empty";
  }
  if (!attestation.renderer.debug_renderer_info) {
    return "webgl_debug_renderer_info_unavailable";
  }
  if (
    !attestation.renderer.unmasked_vendor.trim() ||
    !attestation.renderer.unmasked_renderer.trim()
  ) {
    return "webgl_unmasked_renderer_identity_missing";
  }
  const identity = [
    attestation.renderer.masked_vendor,
    attestation.renderer.masked_renderer,
    attestation.renderer.unmasked_vendor,
    attestation.renderer.unmasked_renderer
  ].join(" ");
  const software = identity.match(SOFTWARE_RENDERER)?.[0];
  return software ? `webgl_software_renderer:${software.toLowerCase()}` : null;
}

export async function captureWebglRendererAttestation(
  page: Page
): Promise<WebglRendererAttestation> {
  const captured = await page.locator(".sceneShell canvas").evaluate((canvas) => {
    const element = canvas as HTMLCanvasElement;
    const context = element.getContext("webgl2") || element.getContext("webgl");
    if (!context) return null;
    const debug = context.getExtension("WEBGL_debug_renderer_info") as {
      UNMASKED_VENDOR_WEBGL: number;
      UNMASKED_RENDERER_WEBGL: number;
    } | null;
    const parameter = (key: number) => String(context.getParameter(key) ?? "");
    return {
      context: {
        drawing_buffer_width: context.drawingBufferWidth,
        drawing_buffer_height: context.drawingBufferHeight,
        lost: context.isContextLost(),
        version: parameter(context.VERSION),
        shading_language_version: parameter(context.SHADING_LANGUAGE_VERSION)
      },
      renderer: {
        masked_vendor: parameter(context.VENDOR),
        masked_renderer: parameter(context.RENDERER),
        unmasked_vendor: debug ? parameter(debug.UNMASKED_VENDOR_WEBGL) : "",
        unmasked_renderer: debug ? parameter(debug.UNMASKED_RENDERER_WEBGL) : "",
        debug_renderer_info: Boolean(debug)
      }
    };
  });
  const base: WebglRendererAttestation = {
    schema_version: WEBGL_RENDERER_ATTESTATION_SCHEMA,
    requested_gpu: true,
    classification: "unknown",
    blocker: null,
    context: captured?.context ?? null,
    renderer: captured?.renderer ?? null
  };
  const blocker = webglRendererAttestationBlocker(base);
  return {
    ...base,
    classification: blocker?.startsWith("webgl_software_renderer:")
      ? "software"
      : blocker
        ? "unknown"
        : "hardware",
    blocker
  };
}

export function assertHardwareWebglRendererAttestation(
  attestation: WebglRendererAttestation
): void {
  const recomputed = webglRendererAttestationBlocker(attestation);
  if (
    attestation.schema_version !== WEBGL_RENDERER_ATTESTATION_SCHEMA ||
    attestation.requested_gpu !== true ||
    attestation.blocker !== recomputed ||
    attestation.classification !== (recomputed ? (recomputed.startsWith("webgl_software_renderer:") ? "software" : "unknown") : "hardware")
  ) {
    throw new Error("WebGL renderer attestation fields contradict the captured renderer identity");
  }
  if (recomputed) throw new Error(`WebGL renderer attestation blocked: ${recomputed}`);
}
