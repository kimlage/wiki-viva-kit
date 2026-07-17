// R5/R7 — the sources-view HUD context panels (owner verdict: the quadrant
// cards competed for attention and the gap chip led nowhere).
//
// - SourcesSummaryPanel replaces the quadrant lens cards inside view=sources:
//   four honest rows (pending / overdue / blocked / no-recipe) computed from
//   the SAME payload the layout was built from. A row activates the existing
//   lens=source_state emphasis — presence only, no relayout, nothing moves.
// - SourceGapsPanel is the ranked census behind the "Gaps — N" chip: grouped
//   by diagnostic code, severity-sorted, each row carries the TRUE occurrence
//   count, a short suggested action and a "see on map" jump to the worst
//   station.
// - SourcesFirstRunCard is the compact three-bullet first-run explainer
//   (localStorage-dismissible, reduced-motion safe: plain DOM, zero animation).
//
// All strings via t() (EN+PT parity enforced by the dictionary test).

import { t } from "../../data/i18n";
import { SEMANTIC_VISUAL_TOKENS } from "../../data/visualEncoding";
import type { SemanticVisualToken } from "../../data/visualEncoding";
// Type-only imports: the 3D renderer module never enters this HUD chunk.
import type { GapMarkerSpec, SourceGapGroup, SourceGapSummary } from "../../renderers/scene/parts/source-foundation";
import type { SourceFoundationPayload, SourceFoundationStation } from "../../types";

// Same severity → token mapping the scene's gap markers use (§10.11): the
// panel and the world must never disagree on what a severity looks like.
function severityToken(severity: SourceGapGroup["severity"]): SemanticVisualToken {
  if (severity === "error") return SEMANTIC_VISUAL_TOKENS.quality.states.flagged;
  if (severity === "warning") return SEMANTIC_VISUAL_TOKENS.quality.states.warning;
  return SEMANTIC_VISUAL_TOKENS.attention.states.quiet;
}

// ---------------------------------------------------------------------------
// Pure models (unit-tested)

export type SourcesSummaryModel = {
  /** TRUE payload totals — never a visible slice. */
  pending: number;
  overdue: number;
  blocked: number;
  noRecipe: number;
};

export function sourcesSummaryModel(payload: SourceFoundationPayload): SourcesSummaryModel {
  const sources = payload.stations.filter((station) => station.kind === "source");
  return {
    pending: payload.summary.pending_streams,
    overdue: payload.streams.filter((stream) => stream.breached).length,
    blocked: payload.summary.blocked_sources,
    noRecipe: sources.filter((station) => station.recipe_state === "missing").length
  };
}

/** The suggested first click (R7): the source station that most needs an
 * operator — ranked by diagnostic pressure, then pending streams, then id for
 * determinism. Null when every station is quiet. */
export function suggestedAttentionStation(
  payload: SourceFoundationPayload | undefined
): Pick<SourceFoundationStation, "canonical_page_id" | "title"> | null {
  if (!payload) return null;
  const candidates = payload.stations
    .filter((station) => station.kind === "source")
    .filter((station) => station.diagnostic_codes.length > 0 || station.pending_stream_count > 0)
    .sort(
      (a, b) =>
        b.diagnostic_codes.length - a.diagnostic_codes.length ||
        b.pending_stream_count - a.pending_stream_count ||
        a.canonical_page_id.localeCompare(b.canonical_page_id)
    );
  const best = candidates[0];
  return best ? { canonical_page_id: best.canonical_page_id, title: best.title } : null;
}

// The diagnostic codes with a dedicated suggested-action string; anything
// outside this vocabulary falls back to the generic action (never a raw key).
const GAP_ACTION_CODES = new Set([
  "source_recipe_missing",
  "source_recipe_invalid",
  "source_recipe_secret_detected",
  "source_lifecycle_missing",
  "source_never_synced",
  "source_sync_failed",
  "source_blocked",
  "stream_never_observed",
  "stream_past_cadence",
  "stream_target_missing",
  "target_without_emission",
  "emission_without_source",
  "emission_without_target",
  "event_without_closure",
  "multiple_sources_supported",
  "relation_outside_source_vocabulary",
  "unresolved_canonical_page"
]);

export function gapActionText(code: string): string {
  return t(GAP_ACTION_CODES.has(code) ? `source_foundation.gaps.action.${code}` : "source_foundation.gaps.action.generic");
}

export const SOURCES_FIRST_RUN_STORAGE_KEY = "wiki.viva.sources.firstRun.v1";

export function sourcesFirstRunDismissed(storage: Pick<Storage, "getItem"> | null): boolean {
  try {
    return storage?.getItem(SOURCES_FIRST_RUN_STORAGE_KEY) === "dismissed";
  } catch {
    return true;
  }
}

export function persistSourcesFirstRunDismissed(storage: Pick<Storage, "setItem"> | null): void {
  try {
    storage?.setItem(SOURCES_FIRST_RUN_STORAGE_KEY, "dismissed");
  } catch {
    // Private mode: the card simply reappears next session.
  }
}

// ---------------------------------------------------------------------------
// R5 — the compact "Sources" summary panel (replaces the quadrant cards).

export function SourcesSummaryPanel({
  payload,
  gapTotal,
  lensActive,
  onToggleLens,
  onOpenGaps
}: {
  payload: SourceFoundationPayload;
  /** TRUE occurrence total from the resolved layout census (the chip number). */
  gapTotal: number | null;
  lensActive: boolean;
  onToggleLens: () => void;
  onOpenGaps: () => void;
}) {
  const model = sourcesSummaryModel(payload);
  const rows: { key: keyof SourcesSummaryModel; label: string; count: number }[] = [
    { key: "pending", label: t("source_foundation.summary.pending"), count: model.pending },
    { key: "overdue", label: t("source_foundation.summary.overdue"), count: model.overdue },
    { key: "blocked", label: t("source_foundation.summary.blocked"), count: model.blocked },
    { key: "noRecipe", label: t("source_foundation.summary.noRecipe"), count: model.noRecipe }
  ];
  return (
    <aside className="sourcesSummaryPanel" aria-label={t("source_foundation.summary.aria")} data-sources-summary>
      <header>
        <strong>{t("source_foundation.summary.title")}</strong>
        <small>{t("source_foundation.band.count.foundation", { n: payload.summary.sources })}</small>
      </header>
      <ul>
        {rows.map((row) => (
          <li key={row.key}>
            <button
              type="button"
              data-sources-summary-row={row.key}
              aria-pressed={lensActive}
              title={lensActive ? t("source_foundation.summary.lensOff") : t("source_foundation.summary.lensHint")}
              onClick={onToggleLens}
            >
              <span>{row.label}</span>
              <strong>{row.count}</strong>
            </button>
          </li>
        ))}
      </ul>
      {gapTotal !== null && gapTotal > 0 && (
        <button type="button" className="sourcesSummaryGaps" data-sources-summary-gaps onClick={onOpenGaps}>
          {t("source_foundation.gaps.chip", { n: gapTotal })}
        </button>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// R5 — the ranked gaps panel behind the "Gaps — N" chip.

export function SourceGapsPanel({
  summary,
  onSeeOnMap,
  onClose
}: {
  summary: SourceGapSummary;
  /** Focus the group's worst diagnostic in the world/dock. */
  onSeeOnMap: (marker: GapMarkerSpec) => void;
  onClose: () => void;
}) {
  return (
    <aside className="sourceGapsPanel" aria-label={t("source_foundation.gaps.panelAria")} data-gaps-panel data-gap-total={summary.total}>
      <header>
        <strong>{t("source_foundation.gaps.panelTitle", { n: summary.total })}</strong>
        <button type="button" className="textButton" aria-label={t("source_foundation.gaps.close")} onClick={onClose}>
          ×
        </button>
      </header>
      <ul>
        {summary.groups.map((group) => {
          const token = severityToken(group.severity);
          const worst = group.markers[0];
          return (
            <li key={group.code} data-gap-group={group.code} data-gap-severity={group.severity}>
              <div className="sourceGapsRowHead">
                <b aria-hidden="true" style={{ color: token.color }}>{token.symbol}</b>
                <span className="sourceGapsLabel">{group.label}</span>
                <strong title={t("source_foundation.gaps.occurrences", { n: group.occurrenceCount })}>
                  {group.occurrenceCount}
                </strong>
              </div>
              <div className="sourceGapsRowBody">
                <small>{gapActionText(group.code)}</small>
                {worst && (
                  <button
                    type="button"
                    className="textButton"
                    data-gap-see-map={group.code}
                    onClick={() => onSeeOnMap(worst)}
                  >
                    {t("source_foundation.gaps.seeMap")}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// R7 — the first-run card (three bullets, dismissible, no motion).

export function SourcesFirstRunCard({
  suggestion,
  onOpenSuggestion,
  onDismiss
}: {
  suggestion: Pick<SourceFoundationStation, "canonical_page_id" | "title"> | null;
  onOpenSuggestion: (pageId: string) => void;
  onDismiss: (options: { never: boolean }) => void;
}) {
  return (
    <aside className="sourcesFirstRun" role="note" aria-label={t("source_foundation.firstRun.title")} data-sources-first-run>
      <strong>{t("source_foundation.firstRun.title")}</strong>
      <ul>
        <li>{t("source_foundation.firstRun.what")}</li>
        <li>
          {t("source_foundation.firstRun.firstClick")}
          {suggestion && (
            <button
              type="button"
              className="textButton"
              data-first-run-open={suggestion.canonical_page_id}
              onClick={() => onOpenSuggestion(suggestion.canonical_page_id)}
            >
              {t("source_foundation.firstRun.open", { label: suggestion.title })}
            </button>
          )}
        </li>
        <li>{t("source_foundation.firstRun.help")}</li>
      </ul>
      <footer>
        <button type="button" onClick={() => onDismiss({ never: false })}>
          {t("source_foundation.firstRun.dismiss")}
        </button>
        <button type="button" data-first-run-never onClick={() => onDismiss({ never: true })}>
          {t("source_foundation.firstRun.never")}
        </button>
      </footer>
    </aside>
  );
}
