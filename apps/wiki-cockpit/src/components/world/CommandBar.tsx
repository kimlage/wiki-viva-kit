// BOTTOM command bar: search field, dock destinations (the old left rail
// dissolved into the world — each exists only when a block on the stack
// provides its surface and carries its live waiting count), perspective
// glyphs, and the tray / missions / work / demo / tour buttons.

import {
  Activity,
  Boxes,
  Database,
  GitPullRequest,
  Inbox,
  ListChecks,
  Search,
  ShieldCheck,
  Sparkles,
  Sprout,
  Trophy
} from "lucide-react";
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from "react";
import { t } from "../../data/i18n";
import { perspectiveLabel } from "../../data/presentation";
import type { Instruments } from "../../data/surfaces";
import { HelpTip } from "../HelpTip";
import type { PerspectiveId, WorldPatch, WorldRoute } from "../../router";
import type { WorldCondition } from "../../scene/condition";

export function CommandBar({
  route,
  activePerspective,
  showCompatibilityPerspectives,
  instruments,
  condition,
  changedCount,
  openMissionCount,
  trayOpen,
  missionsOpen,
  canComposeBrief,
  searchRef,
  searchDraft,
  onSearchDraft,
  onSearchKeyDown,
  onNavigateWorld,
  onCloseTrays,
  onToggleTray,
  onToggleMissions,
  onOpenTour
}: {
  route: WorldRoute;
  activePerspective?: string;
  showCompatibilityPerspectives: boolean;
  instruments: Instruments;
  condition: WorldCondition;
  changedCount: number;
  openMissionCount: number;
  trayOpen: boolean;
  missionsOpen: boolean;
  canComposeBrief: boolean;
  searchRef: RefObject<HTMLInputElement>;
  searchDraft: string;
  onSearchDraft: (value: string) => void;
  onSearchKeyDown: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
  onNavigateWorld: (patch: WorldPatch) => void;
  onCloseTrays: () => void;
  onToggleTray: () => void;
  onToggleMissions: () => void;
  onOpenTour: () => void;
}) {
  const pressedPerspective = activePerspective ?? route.perspective;
  return (
    <div className="worldCommandBar" role="toolbar" aria-label={t("world.commandBarAria")}>
      <label className="commandSearch">
        <Search size={14} aria-hidden />
        <input
          ref={searchRef}
          value={searchDraft}
          onChange={(event) => onSearchDraft(event.target.value)}
          onKeyDown={onSearchKeyDown}
          placeholder={t("world.searchPlaceholder")}
          aria-label={t("world.searchAria")}
        />
      </label>
      {/* Destinations — the old left rail, dissolved into the world. Each
          opens its dock in place (deep-linkable ?dock=…). A destination
          EXISTS only when a block on the stack provides its surface
          (composeInstruments is the one gate) and CARRIES ITS MISSION:
          a live count of the work waiting behind it + a purpose tooltip. */}
      <div className="commandDocks" role="group" aria-label={t("world.destinationsAria")}>
        {([
          {
            dock: "approve",
            label: t("nav.approve"),
            icon: <GitPullRequest size={15} />,
            count: changedCount,
            tone: "warn" as const
          },
          { dock: "intake", label: t("nav.add"), icon: <Inbox size={15} />, count: 0, tone: "warn" as const },
          { dock: "create", label: t("nav.create"), icon: <Sprout size={15} />, count: 0, tone: "warn" as const },
          { dock: "blocks", label: t("nav.blocks"), icon: <Boxes size={15} />, count: 0, tone: "warn" as const },
          {
            dock: "source",
            label: t("nav.sources"),
            icon: <Database size={15} />,
            count: condition.pendingSourceIntake,
            tone: "warn" as const
          },
          {
            dock: "gates",
            label: t("nav.health"),
            icon: <ShieldCheck size={15} />,
            count: condition.gatesFailing.length,
            tone: "bad" as const
          }
        ] as const).filter((item) => instruments.destinations.includes(item.dock)).map((item) => (
          <button
            key={item.dock}
            className={route.query.dock === item.dock ? "dockButton active" : "dockButton"}
            onClick={() => {
              onCloseTrays();
              onNavigateWorld({ dock: route.query.dock === item.dock ? null : item.dock });
            }}
            title={item.count > 0 ? `${t(`dock.mission.${item.dock}`)} — ${t("dock.waiting", { n: item.count })}` : t(`dock.mission.${item.dock}`)}
            aria-pressed={route.query.dock === item.dock}
            type="button"
          >
            {item.icon}
            <small>{item.label}</small>
            {item.count > 0 && <i className={`dockBadge tone-${item.tone}`}>{item.count}</i>}
          </button>
        ))}
      </div>
      {showCompatibilityPerspectives && (
      <div className="perspectiveGlyphs" role="group" aria-label={t("world.perspectives")}>
        {(["radar", "atlas", "districts", "trails", "quadrants"] as PerspectiveId[])
          .filter((perspective) => instruments.perspectives.includes(perspective))
          .map((perspective, index) => {
          const info = perspectiveLabel(perspective);
          return (
            <button
              key={perspective}
              className={pressedPerspective === perspective ? "glyphButton active" : "glyphButton"}
              onClick={() => onNavigateWorld({ perspective })}
              title={`${info.label} (${index + 1}) — ${info.hint}`}
              aria-pressed={pressedPerspective === perspective}
              type="button"
            >
              <span aria-hidden>{info.glyph}</span>
              <small>{info.label}</small>
            </button>
          );
        })}
        {/* Focus is page-triggered — enabled only with a page locked, so it
            never claims to show lenses over nothing. */}
        {(() => {
          const info = perspectiveLabel("focus");
          const enabled = Boolean(route.pageId);
          return (
            <button
              key="focus"
              className={pressedPerspective === "focus" ? "glyphButton active" : "glyphButton"}
              onClick={() => enabled && onNavigateWorld({ perspective: "focus" })}
              disabled={!enabled}
              title={enabled ? `${info.label} (F) — ${info.hint}` : t("perspective.focus.needsPage")}
              aria-pressed={pressedPerspective === "focus"}
              type="button"
            >
              <span aria-hidden>{info.glyph}</span>
              <small>{info.label}</small>
            </button>
          );
        })()}
      </div>
      )}
      {/* The packet tray exists only while it HAS pages — an empty
          collector is noise; the reader's "add to packet" brings it back. */}
      {(route.query.packet.length > 0 || trayOpen) && (
        <>
          <button
            className={trayOpen ? "trayButton active" : "trayButton"}
            onClick={onToggleTray}
            title={t("dock.mission.packet")}
            type="button"
            aria-expanded={trayOpen}
          >
            <ListChecks size={14} />
            <span>{t("world.packet", { n: route.query.packet.length })}</span>
          </button>
          <HelpTip term="packet" />
        </>
      )}
      {instruments.missionsEnabled && (
        <button
          className={missionsOpen ? "trayButton missionsButton active" : "trayButton missionsButton"}
          onClick={onToggleMissions}
          title={openMissionCount > 0 ? `${t("dock.mission.missions")} — ${t("dock.waiting", { n: openMissionCount })}` : t("dock.mission.missions")}
          type="button"
          aria-expanded={missionsOpen}
        >
          <Trophy size={14} />
          <span>{t("world.missions")}</span>
          {openMissionCount > 0 && <i className="dockBadge tone-warn">{openMissionCount}</i>}
        </button>
      )}
      {canComposeBrief && (
        <button
          className={route.query.dock === "work" ? "trayButton workButton active" : "trayButton workButton"}
          onClick={() => {
            // The Work surface is a DOCK (deep-linkable URL state), not a
            // local tray: monitoring delegated jobs must survive reloads
            // and be shareable. patchWorld closes any open tray for us.
            onCloseTrays();
            onNavigateWorld({ dock: route.query.dock === "work" ? null : "work" });
          }}
          type="button"
          aria-expanded={route.query.dock === "work"}
        >
          <Activity size={14} />
          <span>{t("work.title")}</span>
        </button>
      )}
      <a
        className={route.demo ? "trayButton demoButton active" : "trayButton demoButton"}
        href={route.demo ? "/" : "/demo"}
        title={route.demo ? t("nav.exitDemo") : t("nav.demo")}
      >
        <Sparkles size={14} />
        <span>{route.demo ? t("nav.exitDemo") : t("nav.demo")}</span>
      </a>
      <button className="trayButton tourButton" onClick={onOpenTour} type="button">
        <span aria-hidden>?</span>
        <span className="visuallyHidden">{t("tour.reopen")}</span>
      </button>
      <span className="commandHint" aria-hidden>
        {t("world.hintKeys")}
      </span>
    </div>
  );
}
