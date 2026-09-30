// The abrachaindabra ritual's 2D twin (plan §15.6): when the canvas cannot
// host the spatial ritual (no WebGL, reduced-environment fallback, degraded
// performance budget), a local SVG/CSS Takezo delivers the SAME robe, hat and
// ribbons, the SAME copy and the SAME flow — no administrative capability is
// lost by falling back, and nothing here ever issues a request.

import { t } from "../data/i18n";
import { TAKEZO_PALETTE, TakezoSpeechContent } from "../renderers/scene/parts/TakezoWizard";
import type { TakezoRuntimeKind, TakezoSpeechHandlers } from "../renderers/scene/parts/TakezoWizard";
import { TAKEZO_CHAIN_COLOR } from "../renderers/scene/parts/TakezoPortal";

/**
 * Which §5.3 voice the ritual uses for this runtime. Anything without a
 * reachable operator (static bundles, unknown adapters) shares the sealed
 * demo contemplation copy — the honest default is "nothing can be rewritten".
 */
export function takezoRuntimeKind(demoRoute: boolean, runtimeMode: string): TakezoRuntimeKind {
  if (demoRoute) return "demo";
  if (runtimeMode === "sample_fallback") return "sample";
  if (runtimeMode === "local_operator") return "local";
  return "demo";
}

// A hand-drawn local illustration — same identity as the procedural build:
// blue robe, blue hat, red ribbons, emissive eyes, chain arc. Decorative for
// screen readers beyond its alt text (plan §15.6).
function TakezoFigure() {
  return (
    <svg
      className="takezoFigure"
      viewBox="0 0 160 170"
      role="img"
      aria-label={t("takezo.alt")}
      focusable="false"
    >
      {/* Chain arc — the abra-CHAIN-dabra pun, not a count. */}
      <g fill="none" stroke={TAKEZO_CHAIN_COLOR} strokeWidth="3" opacity="0.85">
        <circle cx="24" cy="120" r="6" />
        <circle cx="30" cy="94" r="6" />
        <circle cx="44" cy="70" r="6" />
        <circle cx="66" cy="52" r="6" />
        <circle cx="94" cy="52" r="6" />
        <circle cx="116" cy="70" r="6" />
        <circle cx="130" cy="94" r="6" />
        <circle cx="136" cy="120" r="6" />
      </g>
      {/* Tail */}
      <path
        d="M104 150 C 126 146, 132 128, 124 116"
        fill="none"
        stroke={TAKEZO_PALETTE.fur}
        strokeWidth="7"
        strokeLinecap="round"
      />
      {/* Robe — truncated cone silhouette */}
      <path d="M62 96 L98 96 L112 152 L48 152 Z" fill={TAKEZO_PALETTE.robe} />
      {/* Ears */}
      <path d="M62 74 L68 56 L76 72 Z" fill={TAKEZO_PALETTE.fur} />
      <path d="M98 74 L92 56 L84 72 Z" fill={TAKEZO_PALETTE.fur} />
      {/* Head */}
      <circle cx="80" cy="86" r="20" fill={TAKEZO_PALETTE.fur} />
      {/* Emissive eyes */}
      <circle cx="73" cy="86" r="2.6" fill={TAKEZO_PALETTE.eyes} />
      <circle cx="87" cy="86" r="2.6" fill={TAKEZO_PALETTE.eyes} />
      {/* Hat: brim + inclined cone */}
      <ellipse cx="80" cy="68" rx="26" ry="6" fill={TAKEZO_PALETTE.hat} />
      <path d="M62 66 L86 24 L98 66 Z" fill={TAKEZO_PALETTE.hat} />
      {/* Red ribbons on the hat — costume, never risk. */}
      <path
        d="M98 66 C 106 76, 104 88, 98 96"
        fill="none"
        stroke={TAKEZO_PALETTE.ribbon}
        strokeWidth="4"
        strokeLinecap="round"
      />
      <path
        d="M96 64 C 108 68, 114 78, 112 88"
        fill="none"
        stroke={TAKEZO_PALETTE.ribbon}
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * The full-surface fallback ritual: figure + the shared speech plate (same
 * copy, same actions, same focus/Escape behavior as the in-world plate).
 */
export function TakezoRitualFallback({ runtime, onUnlock, onClose }: TakezoSpeechHandlers) {
  return (
    <div className="takezoRitualFallback" data-takezo-runtime={runtime}>
      <TakezoFigure />
      <TakezoSpeechContent runtime={runtime} onUnlock={onUnlock} onClose={onClose} />
    </div>
  );
}
