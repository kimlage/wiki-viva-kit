// The LEFT mission surface. Collapsed by choice it is a single honest chip
// (worst tone + pending count) — the world stays visible; expanded it is the
// do-now card. Search results always render: the keyboard search flow must
// never depend on the card state.

import { Sparkles } from "lucide-react";
import { t } from "../../data/i18n";
import { contextLabel, isRawData, perspectiveLabel } from "../../data/presentation";
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
  // Optional secondary action (e.g. "resolve with Codex") rendered as a button
  // beside the row's main click target.
  action?: { label: string; title?: string; onClick: () => void };
};

export function MissionCard({
  rows,
  perspective,
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
  perspective: string;
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
          title={perspectiveLabel(perspective).hint}
          type="button"
        >
          <i aria-hidden />
          <strong>{perspectiveLabel(perspective).label}</strong>
          <span>
            {actionable.length > 0 ? t("world.missionCount", { n: actionable.length }) : t("world.missionClear")}
          </span>
        </button>
        {searchBlock && <div className="worldMissionCard searchOnly">{searchBlock}</div>}
      </div>
    );
  }
  return (
    <div className="worldMissionCard" role="region" aria-label={t("world.missionAria")}>
      <header>
        <strong>{perspectiveLabel(perspective).label}</strong>
        <span>{perspectiveLabel(perspective).hint}</span>
        <button className="readerClose missionCollapse" onClick={onToggle} title={t("world.missionCollapse")} type="button">
          –
        </button>
      </header>
      <div className="missionRows">
        {rows.slice(0, 3).map((row, index) => (
          <div className={`missionRow tone-${row.tone}`} key={row.key}>
            <button className="missionRowMain" onClick={row.onClick} type="button">
              <span className="stageIndex">{index + 1}</span>
              <span className="missionCopy">
                <strong>{row.label}</strong>
                <small>{row.detail}</small>
              </span>
            </button>
            {row.action && (
              <button className="missionRowAction" onClick={row.action.onClick} title={row.action.title} type="button">
                <Sparkles size={13} />
                <span>{row.action.label}</span>
              </button>
            )}
            {row.help && <HelpTip title={row.label} body={row.help} />}
          </div>
        ))}
      </div>
      {searchBlock}
    </div>
  );
}
