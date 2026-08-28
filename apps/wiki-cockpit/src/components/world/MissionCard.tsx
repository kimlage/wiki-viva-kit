// The LEFT mission surface. Collapsed by choice it is a single honest chip
// (worst tone + pending count) — the world stays visible; expanded it is the
// do-now card. Search results always render: the keyboard search flow must
// never depend on the card state.

import { useId } from "react";
import { Sparkles } from "lucide-react";
import { t } from "../../data/i18n";
import { contextLabel, isRawData, pageTypeLabel } from "../../data/presentation";
import type { SearchFacet } from "../../scene/search";
import type { PageRecord } from "../../types";
import { HelpTip } from "../HelpTip";

export const SEARCH_VISIBLE = 10;
export const SEARCH_RESULTS_ID = "world-search-results";
export const searchResultOptionId = (index: number) => `${SEARCH_RESULTS_ID}-option-${index}`;

export type MissionRow = {
  key: string;
  label: string;
  detail: string;
  help?: string;
  tone: "good" | "warn" | "bad";
  onClick: () => void;
  // Optional secondary action (e.g. "resolve with Codex") rendered in the
  // row's dedicated action band, never beside/compressing the main copy.
  action?: { label: string; title?: string; disabled?: boolean; onClick?: () => void };
};

export function MissionCard({
  rows,
  viewLabel,
  viewHint,
  viewBadge,
  overlayLabel,
  missionsEnabled,
  open,
  onToggle,
  query,
  searchHits,
  visibleHits,
  activeHit,
  searchType,
  searchContext,
  searchScope,
  searchPageTypes,
  searchContexts,
  onActiveHit,
  onOpenHit,
  onSearchFilter,
  onShowMore
}: {
  rows: MissionRow[];
  viewLabel: string;
  viewHint: string;
  viewBadge?: string;
  overlayLabel: string;
  missionsEnabled: boolean;
  open: boolean;
  onToggle: () => void;
  query: string;
  searchHits: PageRecord[];
  visibleHits: PageRecord[];
  activeHit: number;
  searchType: string;
  searchContext: string;
  searchScope: "" | "world";
  searchPageTypes: SearchFacet[];
  searchContexts: SearchFacet[];
  onActiveHit: (index: number) => void;
  onOpenHit: (page?: PageRecord) => void;
  onSearchFilter: (patch: {
    searchType?: string | null;
    searchContext?: string | null;
    searchScope?: "world" | null;
  }) => void;
  onShowMore: () => void;
}) {
  const panelId = useId();
  const titleId = `${panelId}-title`;
  const actionable = rows.filter((row) => row.key !== "browse");
  const worstTone = actionable.some((row) => row.tone === "bad")
    ? "bad"
    : actionable.some((row) => row.tone === "warn")
      ? "warn"
      : "good";
  const typeFacets = searchType && !searchPageTypes.some((facet) => facet.value === searchType)
    ? [{ value: searchType, count: 0 }, ...searchPageTypes]
    : searchPageTypes;
  const contextFacets = searchContext && !searchContexts.some((facet) => facet.value === searchContext)
    ? [{ value: searchContext, count: 0 }, ...searchContexts]
    : searchContexts;
  const searchBlock = query ? (
    <div className="missionSearchResults">
      <span className="missionSearchCount" role="status" aria-live="polite">
        {searchHits.length > SEARCH_VISIBLE
          ? t("world.resultsCapped", { n: searchHits.length, shown: visibleHits.length })
          : t("world.results", { n: searchHits.length })}
      </span>
      <div className="searchFacetControls" role="group" aria-label={t("world.searchFiltersAria")}>
        <label>
          <span>{t("world.searchType")}</span>
          <select
            aria-label={t("world.searchType")}
            value={searchType}
            onChange={(event) => onSearchFilter({ searchType: event.target.value || null })}
          >
            <option value="">{t("world.searchAllTypes")}</option>
            {typeFacets.map((facet) => (
              <option key={facet.value} value={facet.value}>
                {pageTypeLabel(facet.value)} · {facet.count}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("world.searchContext")}</span>
          <select
            aria-label={t("world.searchContext")}
            value={searchContext}
            onChange={(event) => onSearchFilter({ searchContext: event.target.value || null })}
          >
            <option value="">{t("world.searchAllContexts")}</option>
            {contextFacets.map((facet) => (
              <option key={facet.value} value={facet.value}>
                {contextLabel(facet.value)} · {facet.count}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("world.searchScope")}</span>
          <select
            aria-label={t("world.searchScope")}
            value={searchScope}
            onChange={(event) => onSearchFilter({ searchScope: event.target.value === "world" ? "world" : null })}
          >
            <option value="">{t("world.searchScopeGlobal")}</option>
            <option value="world">{t("world.searchScopeWorld")}</option>
          </select>
        </label>
      </div>
      <div
        className="searchResultList"
        id={SEARCH_RESULTS_ID}
        role="listbox"
        aria-label={t("world.results", { n: searchHits.length })}
      >
        {visibleHits.map((page, index) => (
          <button
            className={index === activeHit ? "textButton searchHitActive" : "textButton"}
            id={searchResultOptionId(index)}
            key={page.id}
            role="option"
            aria-selected={index === activeHit}
            // Pointer intent, not layout motion, owns the active option. An
            // expanding/refiltered list can move under a stationary cursor;
            // mouseenter would then overwrite keyboard selection without the
            // user moving the pointer at all.
            onPointerMove={() => onActiveHit(index)}
            onClick={() => onOpenHit(page)}
            title={page.path}
            type="button"
          >
            {page.title}
            <small>
              {" "}
              · {pageTypeLabel(page.page_type)} · {contextLabel(page.context || "system")}
              {isRawData(page.page_type) ? <em className="rawTag"> {t("world.raw")}</em> : null}
              {page.summary_truncated ? ` · ${t("world.partialSummary")}` : ""}
            </small>
          </button>
        ))}
      </div>
      {visibleHits.length < searchHits.length && (
        <button className="searchShowMore" onClick={onShowMore} type="button">
          {t("world.searchShowMore", {
            n: Math.min(SEARCH_VISIBLE, searchHits.length - visibleHits.length),
            remaining: searchHits.length - visibleHits.length
          })}
        </button>
      )}
      {searchHits.length === 0 && <span className="missionSearchCount">{t("world.noResults")}</span>}
    </div>
  ) : null;
  // No gamification package → no mission surface at all. Search results
  // still render (the keyboard flow never depends on missions).
  if (!missionsEnabled) {
    return searchBlock ? (
      <div
        className="worldMissionSlim"
        role="region"
        aria-label={t("world.missionAria")}
        data-search-active="true"
      >
        <div className="worldMissionCard searchOnly">{searchBlock}</div>
      </div>
    ) : null;
  }
  if (!open) {
    return (
      <div
        className="worldMissionSlim"
        role="region"
        aria-label={t("world.missionAria")}
        data-search-active={query ? "true" : undefined}
      >
        <button
          className={`worldMissionChip tone-${worstTone}`}
          onClick={onToggle}
          aria-expanded={false}
          aria-controls={panelId}
          title={`${viewHint} · ${overlayLabel}`}
          data-view-context={viewBadge ? "compatibility" : "native"}
          type="button"
        >
          <i aria-hidden />
          {viewBadge && <small className="missionViewBadge">{viewBadge}</small>}
          <strong>{viewLabel}</strong>
          <span>
            {actionable.length > 0 ? t("world.missionCount", { n: actionable.length }) : t("world.missionClear")}
          </span>
        </button>
        {searchBlock && <div className="worldMissionCard searchOnly">{searchBlock}</div>}
      </div>
    );
  }
  return (
    <div
      className="worldMissionCard"
      id={panelId}
      role="region"
      aria-labelledby={titleId}
      data-search-active={query ? "true" : undefined}
    >
      <header>
        <strong id={titleId}>{t("world.nextSteps")}</strong>
        <span className="missionContextSummary" data-view-context={viewBadge ? "compatibility" : "native"}>
          {viewBadge && <span className="missionViewBadge">{viewBadge}</span>}
          <span className="missionViewContext">{viewLabel}</span>
          <span aria-hidden> · </span>
          <span className="missionViewHint">{viewHint}</span>
          <span aria-hidden> · </span>
          <span className="missionOverlayContext">{overlayLabel}</span>
        </span>
        <button
          className="readerClose missionCollapse"
          onClick={onToggle}
          aria-controls={panelId}
          aria-expanded={true}
          title={t("world.missionCollapse")}
          type="button"
        >
          –
        </button>
      </header>
      <div className="missionRows">
        {rows.slice(0, 3).map((row, index) => {
          const rowTitleId = `${panelId}-row-${index}-title`;
          const rowDetailId = `${panelId}-row-${index}-detail`;
          return (
            <div className={`missionRow tone-${row.tone}`} key={row.key}>
              <button className="missionRowMain" onClick={row.onClick} aria-describedby={rowDetailId} type="button">
                <span className="stageIndex">{index + 1}</span>
                <span className="missionCopy">
                  <strong id={rowTitleId}>{row.label}</strong>
                  <small id={rowDetailId}>{row.detail}</small>
                </span>
              </button>
              {(row.action || row.help) && (
                <div
                  className="missionRowActions"
                  role="group"
                  aria-labelledby={rowTitleId}
                  style={{ flexBasis: "100%", minWidth: 0 }}
                >
                  {row.action && (
                    <button
                      className="missionRowAction"
                      onClick={row.action.disabled ? undefined : row.action.onClick}
                      title={row.action.title}
                      disabled={row.action.disabled}
                      aria-label={row.action.disabled ? `${row.action.label} — ${row.action.title || t("demo.readOnlyControl")}` : undefined}
                      type="button"
                    >
                      <Sparkles size={13} />
                      <span>{row.action.label}</span>
                    </button>
                  )}
                  {row.help && <HelpTip title={row.label} body={row.help} />}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {searchBlock}
    </div>
  );
}
