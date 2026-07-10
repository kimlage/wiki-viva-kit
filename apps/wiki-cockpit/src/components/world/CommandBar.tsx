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
import { useLayoutEffect, useRef } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from "react";
import { t } from "../../data/i18n";
import { perspectiveLabel } from "../../data/presentation";
import { isNativeWorldViewId } from "../../world/experience";
import type { Instruments } from "../../data/surfaces";
import { HelpTip } from "../HelpTip";
import type { PerspectiveId, WorldPatch, WorldRoute } from "../../router";
import type { WorldCondition } from "../../scene/condition";

const COMPATIBILITY_PERSPECTIVE_ORDER = ["radar", "atlas", "districts", "trails", "quadrants"] as const satisfies readonly PerspectiveId[];

export function visibleCompatibilityPerspectives(
  activePerspective: string,
  availablePerspectives: readonly PerspectiveId[]
): PerspectiveId[] {
  const available = new Set(availablePerspectives);
  // The active legacy deep link remains visible as honest current context even
  // when the template does not offer it. No other hidden perspective leaks
  // into discovery, and the template-owned list is never mutated.
  return COMPATIBILITY_PERSPECTIVE_ORDER.filter(
    (perspective) => available.has(perspective) || perspective === activePerspective
  );
}

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
  const compatibilityPerspectives = visibleCompatibilityPerspectives(pressedPerspective, instruments.perspectives);
  const barRef = useRef<HTMLDivElement>(null);

  // The command bar wraps according to both the available width and the
  // platform's font metrics. Publish its measured height to the scene shell so
  // sibling HUD surfaces can reserve the real hit region instead of guessing
  // from a single desktop screenshot.
  useLayoutEffect(() => {
    const bar = barRef.current;
    const sceneShell = bar?.closest<HTMLElement>(".sceneShell");
    if (!bar || !sceneShell) return;

    const publishHeight = () => {
      sceneShell.style.setProperty("--world-command-bar-height", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
    };
    publishHeight();

    if (typeof ResizeObserver === "undefined") {
      return () => sceneShell.style.removeProperty("--world-command-bar-height");
    }
    const observer = new ResizeObserver(publishHeight);
    observer.observe(bar);
    return () => {
      observer.disconnect();
      sceneShell.style.removeProperty("--world-command-bar-height");
    };
  }, []);

  return (
    <div ref={barRef} className="worldCommandBar" role="toolbar" aria-label={t("world.commandBarAria")}>
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
        {compatibilityPerspectives.map((perspective, index) => {
          const info = perspectiveLabel(perspective);
          const currentOnly = pressedPerspective === perspective &&
            !isNativeWorldViewId(perspective) &&
            !instruments.perspectives.includes(perspective);
          return (
            <button
              key={perspective}
              className={pressedPerspective === perspective
                ? currentOnly ? "glyphButton active compatibilityCurrent" : "glyphButton active"
                : "glyphButton"}
              onClick={() => onNavigateWorld({ perspective })}
              title={currentOnly
                ? `${t("world.experience.compatibility.badge")}: ${info.label} — ${info.hint}`
                : `${info.label} (${index + 1}) — ${info.hint}`}
              aria-pressed={pressedPerspective === perspective}
              data-perspective-option={perspective}
              data-compatibility-current-only={currentOnly ? "true" : "false"}
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
