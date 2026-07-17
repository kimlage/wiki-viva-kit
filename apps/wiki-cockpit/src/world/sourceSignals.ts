// Ephemeral scene <-> SourceDock signals for the source-foundation profile.
//
// §12.3: focusing a stream port opens the SourceDock and focuses that stream's
// row. The focus is EPHEMERAL by design — no URL parameter (derived stream ids
// are not yet proven deep-link stable across recipe changes) and no breadcrumb
// change. §12.6: trace highlights are selection-driven inspection state, never
// a view. Both signals therefore travel as window events between the scene
// (mounted inside WorldView) and the App-mounted SourceDock instead of route
// state — the same cross-cutting event pattern the runtime performance
// fallback already uses (world/performance.ts).

import type { SourceFoundationPayload } from "../types";

export const SOURCE_STREAM_FOCUS_EVENT = "wiki:source-stream-focus";
export const SOURCE_TRACE_EVENT = "wiki:source-trace-highlight";

export type SourceStreamFocusDetail = {
  /** Canonical source page id that owns the activated port. */
  sourceId: string;
  /** DERIVED foundation stream id (`stream:` prefix); null on the aggregated "+N" overflow port. */
  streamId: string | null;
};

export type SourceTraceMode = "upstream" | "downstream" | "closure";

/** null clears the highlight (dock closed / trace toggled off). */
export type SourceTraceDetail = { mode: SourceTraceMode; subjectId: string } | null;

export function dispatchSourceStreamFocus(detail: SourceStreamFocusDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<SourceStreamFocusDetail>(SOURCE_STREAM_FOCUS_EVENT, { detail }));
}

export function subscribeSourceStreamFocus(listener: (detail: SourceStreamFocusDetail) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<SourceStreamFocusDetail>).detail;
    if (detail && typeof detail.sourceId === "string") listener(detail);
  };
  window.addEventListener(SOURCE_STREAM_FOCUS_EVENT, handler);
  return () => window.removeEventListener(SOURCE_STREAM_FOCUS_EVENT, handler);
}

export function dispatchSourceTrace(detail: SourceTraceDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<SourceTraceDetail>(SOURCE_TRACE_EVENT, { detail }));
}

export function subscribeSourceTrace(listener: (detail: SourceTraceDetail) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<SourceTraceDetail>).detail;
    listener(detail && typeof detail.subjectId === "string" ? detail : null);
  };
  window.addEventListener(SOURCE_TRACE_EVENT, handler);
  return () => window.removeEventListener(SOURCE_TRACE_EVENT, handler);
}

// The scene speaks derived stream ids; the SourceDock's stream table speaks
// recipe stream ids (SourceEntity.streams[].id). Resolve the ephemeral focus
// across that boundary here so no derived id ever reaches the dock DOM — and
// certainly never a URL.
export function resolveFocusedStreamId(
  payload: SourceFoundationPayload | undefined,
  detail: SourceStreamFocusDetail | null
): string | null {
  if (!detail || !detail.streamId || !payload) return null;
  const match = payload.streams.find(
    (stream) => stream.stream_id === detail.streamId && stream.source_id === detail.sourceId
  );
  return match ? match.recipe_stream_id : null;
}
