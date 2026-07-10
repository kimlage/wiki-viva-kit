// The LEFT mission surface. Collapsed by choice it is a single honest chip
// (worst tone + pending count) — the world stays visible; expanded it is the
// do-now card. Search results always render: the keyboard search flow must
// never depend on the card state.

import { useId } from "react";
import { Sparkles } from "lucide-react";
import { t } from "../../data/i18n";
import { contextLabel, isRawData } from "../../data/presentation";
import type { PageRecord } from "../../types";
import { HelpTip } from "../HelpTip";

export const SEARCH_VISIBLE = 10;

export type MissionRow = {
  key: string;
  label: string;
  detail: string;
  help?: string;
  tone: "good" | "warn" | "bad";
  onClick: () => void;
  // Optional secondary action (e.g. "resolve with Codex") rendered in the
  // row's dedicated action band, never beside/compressing the main copy.
  action?: { label: string; title?: string; onClick: () => void };
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
  onActiveHit,
  onOpenHit
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
  onActiveHit: (index: number) => void;
  onOpenHit: (page?: PageRecord) => void;
}) {
  const panelId = useId();
  const titleId = `${panelId}-title`;
  const actionable = rows.filter((row) => row.key !== "browse");
  const worstTone = actionable.some((row) => row.tone === "bad")
    ? "bad"
    : actionable.some((row) => row.tone === "warn")
      ? "warn"
      : "good";
  const searchBlock = query ? (
    <div className="missionSearchResults" aria-label={t("world.results", { n: searchHits.length })}>
      <span className="missionSearchCount">
        {searchHits.length > SEARCH_VISIBLE
          ? t("world.resultsCapped", { n: searchHits.length, shown: SEARCH_VISIBLE })
          : t("world.results", { n: searchHits.length })}
      </span>
      {visibleHits.map((page, index) => (
        <button
          className={index === activeHit ? "textButton searchHitActive" : "textButton"}
          key={page.id}
          onMouseEnter={() => onActiveHit(index)}
          onClick={() => onOpenHit(page)}
          title={page.path}
          type="button"
        >
          {page.title}
          <small>
            {" "}
            · {contextLabel(page.context || "system")}
            {isRawData(page.page_type) ? <em className="rawTag"> {t("world.raw")}</em> : null}
            {page.summary_truncated ? ` · ${t("world.partialSummary")}` : ""}
          </small>
        </button>
      ))}
      {searchHits.length === 0 && <span className="missionSearchCount">{t("world.noResults")}</span>}
    </div>
  ) : null;
  // No gamification package → no mission surface at all. Search results
  // still render (the keyboard flow never depends on missions).
  if (!missionsEnabled) {
    return searchBlock ? (
      <div className="worldMissionSlim" role="region" aria-label={t("world.missionAria")}>
        <div className="worldMissionCard searchOnly">{searchBlock}</div>
      </div>
    ) : null;
  }
  if (!open) {
    return (
      <div className="worldMissionSlim" role="region" aria-label={t("world.missionAria")}>
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
    <div className="worldMissionCard" id={panelId} role="region" aria-labelledby={titleId}>
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
                    <button className="missionRowAction" onClick={row.action.onClick} title={row.action.title} type="button">
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
