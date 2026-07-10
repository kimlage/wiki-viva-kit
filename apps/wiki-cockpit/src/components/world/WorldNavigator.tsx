import {
  CircleDot,
  Clock3,
  Crosshair,
  Database,
  Eye,
  Grid2X2,
  Info,
  Layers3,
  Link2,
  ListChecks,
  ListTodo,
  Radar,
  ShieldCheck,
  Users,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useId, useState } from "react";
import type { KeyboardEvent } from "react";
import { t } from "../../data/i18n";
import type { LensId, OverlayId } from "../../world/contracts";
import {
  WORLD_EXPERIENCE_AXES,
  WORLD_EXPERIENCE_KEYS,
  WORLD_OVERLAY_EXPERIENCES,
  WORLD_QUADRANT_LENS_EXPERIENCES,
  WORLD_VIEW_EXPERIENCES,
  activeQuadrantLensOption,
  isWorldOverlayId
} from "../../world/experience";
import type {
  ExperienceIconId,
  NativeWorldViewId,
  QuadrantLensSelection
} from "../../world/experience";

export type WorldExperienceTranslate = (key: string) => string;

export type WorldNavigatorProps = {
  view: NativeWorldViewId;
  overlay: OverlayId;
  lens?: LensId | null;
  expanded?: boolean;
  defaultExpanded?: boolean;
  panelId?: string;
  translate?: WorldExperienceTranslate;
  onExpandedChange?: (expanded: boolean) => void;
  onViewChange: (view: NativeWorldViewId) => void;
  onOverlayChange: (overlay: OverlayId) => void;
  onLensChange: (lens: QuadrantLensSelection) => void;
};

const ICONS: Readonly<Record<ExperienceIconId, LucideIcon>> = {
  view: Eye,
  lens: Crosshair,
  overlay: Layers3,
  quadrants: Grid2X2,
  radar: Radar,
  sources: Database,
  work: ListTodo,
  attention: CircleDot,
  freshness: Clock3,
  actions: ListChecks,
  ownership: Users,
  evidence: Link2,
  quality: ShieldCheck
};

function ExperienceIcon({ id, size = 16 }: { id: ExperienceIconId; size?: number }) {
  const Icon = ICONS[id];
  return <Icon size={size} aria-hidden="true" focusable="false" />;
}

export function WorldNavigator({
  view,
  overlay,
  lens,
  expanded,
  defaultExpanded = false,
  panelId,
  translate = t,
  onExpandedChange,
  onViewChange,
  onOverlayChange,
  onLensChange
}: WorldNavigatorProps) {
  const generatedId = useId().replaceAll(":", "");
  const resolvedPanelId = panelId || `world-experience-${generatedId}`;
  const panelHeadingId = `${resolvedPanelId}-title`;
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isExpanded = expanded ?? internalExpanded;
  const selectedLens = activeQuadrantLensOption(lens);

  const changeExpanded = (next: boolean) => {
    if (expanded === undefined) setInternalExpanded(next);
    onExpandedChange?.(next);
  };

  const onPanelKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    changeExpanded(false);
  };

  return (
    <section
      className="worldNavigator"
      aria-label={translate(WORLD_EXPERIENCE_KEYS.compactAria)}
      data-world-view={view}
      data-world-overlay={overlay}
      data-world-lens={selectedLens}
    >
      <div className="worldNavigatorCompact worldRuntimeControls">
        <div
          className="worldNavigatorViewControls worldRuntimeControlGroup"
          role="group"
          aria-label={translate(WORLD_EXPERIENCE_KEYS.viewGroupAria)}
        >
          {WORLD_VIEW_EXPERIENCES.map((option) => (
            <button
              key={option.id}
              type="button"
              className={view === option.id ? "runtimeControl worldNavigatorView active" : "runtimeControl worldNavigatorView"}
              aria-pressed={view === option.id}
              aria-label={translate(option.labelKey)}
              data-view-option={option.id}
              onClick={() => onViewChange(option.id)}
            >
              <ExperienceIcon id={option.icon} />
              <span>{translate(option.labelKey)}</span>
            </button>
          ))}
        </div>

        <label className="worldRuntimeSelect worldNavigatorOverlaySelect">
          <span>{translate(WORLD_EXPERIENCE_KEYS.overlaySelectLabel)}</span>
          <select
            value={overlay}
            aria-label={translate(WORLD_EXPERIENCE_KEYS.overlaySelectLabel)}
            onChange={(event) => {
              if (isWorldOverlayId(event.target.value)) onOverlayChange(event.target.value);
            }}
          >
            {WORLD_OVERLAY_EXPERIENCES.map((option) => (
              <option key={option.id} value={option.id}>
                {translate(option.labelKey)}
              </option>
            ))}
          </select>
        </label>

        <button
          className={isExpanded ? "runtimeControl worldNavigatorLearn active" : "runtimeControl worldNavigatorLearn"}
          type="button"
          aria-expanded={isExpanded}
          aria-controls={resolvedPanelId}
          onClick={() => changeExpanded(!isExpanded)}
        >
          <Info size={16} aria-hidden="true" focusable="false" />
          <span>{translate(WORLD_EXPERIENCE_KEYS.learn)}</span>
        </button>
      </div>

      {isExpanded && (
        <div
          id={resolvedPanelId}
          className="worldNavigatorPanel"
          role="region"
          aria-labelledby={panelHeadingId}
          onKeyDown={onPanelKeyDown}
        >
          <header className="worldNavigatorPanelHeader">
            <div>
              <h2 id={panelHeadingId}>{translate(WORLD_EXPERIENCE_KEYS.panelTitle)}</h2>
              <p>{translate(WORLD_EXPERIENCE_KEYS.panelIntro)}</p>
            </div>
            <button
              className="readerClose worldNavigatorClose"
              type="button"
              aria-label={translate(WORLD_EXPERIENCE_KEYS.close)}
              onClick={() => changeExpanded(false)}
            >
              <X size={17} aria-hidden="true" focusable="false" />
            </button>
          </header>

          <section className="worldNavigatorMentalModel" aria-labelledby={`${resolvedPanelId}-mental-model`}>
            <h3 id={`${resolvedPanelId}-mental-model`}>{translate(WORLD_EXPERIENCE_KEYS.mentalModelTitle)}</h3>
            <ol>
              {WORLD_EXPERIENCE_AXES.map((axis) => (
                <li key={axis.id} data-experience-axis={axis.id}>
                  <ExperienceIcon id={axis.icon} size={17} />
                  <span>
                    <strong>{translate(axis.labelKey)}</strong>
                    <small>{translate(axis.descriptionKey)}</small>
                  </span>
                </li>
              ))}
            </ol>
          </section>

          <section className="worldNavigatorSection" aria-labelledby={`${resolvedPanelId}-views`}>
            <header>
              <h3 id={`${resolvedPanelId}-views`}>{translate(WORLD_EXPERIENCE_KEYS.viewsTitle)}</h3>
              <p>{translate(WORLD_EXPERIENCE_KEYS.viewsIntro)}</p>
            </header>
            <div className="worldNavigatorCardGrid worldNavigatorViewCards">
              {WORLD_VIEW_EXPERIENCES.map((option) => {
                const descriptionId = `${resolvedPanelId}-view-${option.id}`;
                return (
                  <button
                    key={option.id}
                    className={view === option.id ? "worldNavigatorCard active" : "worldNavigatorCard"}
                    type="button"
                    aria-pressed={view === option.id}
                    aria-describedby={descriptionId}
                    data-view-card={option.id}
                    onClick={() => onViewChange(option.id)}
                  >
                    <span className="worldNavigatorCardTitle">
                      <ExperienceIcon id={option.icon} size={18} />
                      <strong>{translate(option.labelKey)}</strong>
                    </span>
                    <span className="worldNavigatorCardQuestion">{translate(option.questionKey)}</span>
                    <small id={descriptionId}>{translate(option.descriptionKey)}</small>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="worldNavigatorSection" aria-labelledby={`${resolvedPanelId}-lenses`}>
            <header>
              <h3 id={`${resolvedPanelId}-lenses`}>{translate(WORLD_EXPERIENCE_KEYS.lensesTitle)}</h3>
              <p>{translate(WORLD_EXPERIENCE_KEYS.lensesIntro)}</p>
            </header>
            <div className="worldNavigatorLensGrid" role="group" aria-labelledby={`${resolvedPanelId}-lenses`}>
              {WORLD_QUADRANT_LENS_EXPERIENCES.map((option) => {
                const descriptionId = `${resolvedPanelId}-lens-${option.id}`;
                return (
                  <button
                    key={option.id}
                    className={selectedLens === option.id ? "worldNavigatorLens active" : "worldNavigatorLens"}
                    type="button"
                    aria-pressed={selectedLens === option.id}
                    aria-describedby={descriptionId}
                    data-lens-option={option.id}
                    onClick={() => onLensChange(option.value)}
                  >
                    <strong>{translate(option.labelKey)}</strong>
                    <small id={descriptionId}>{translate(option.descriptionKey)}</small>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="worldNavigatorSection" aria-labelledby={`${resolvedPanelId}-overlays`}>
            <header>
              <h3 id={`${resolvedPanelId}-overlays`}>{translate(WORLD_EXPERIENCE_KEYS.overlaysTitle)}</h3>
              <p>{translate(WORLD_EXPERIENCE_KEYS.overlaysIntro)}</p>
            </header>
            <div className="worldNavigatorCardGrid worldNavigatorOverlayCards">
              {WORLD_OVERLAY_EXPERIENCES.map((option) => {
                const descriptionId = `${resolvedPanelId}-overlay-${option.id}`;
                return (
                  <button
                    key={option.id}
                    className={overlay === option.id ? "worldNavigatorCard active" : "worldNavigatorCard"}
                    type="button"
                    aria-pressed={overlay === option.id}
                    aria-describedby={descriptionId}
                    data-overlay-card={option.id}
                    onClick={() => onOverlayChange(option.id)}
                  >
                    <span className="worldNavigatorCardTitle">
                      <ExperienceIcon id={option.icon} size={18} />
                      <strong>{translate(option.labelKey)}</strong>
                    </span>
                    <span className="worldNavigatorCardQuestion">{translate(option.questionKey)}</span>
                    <small id={descriptionId}>{translate(option.descriptionKey)}</small>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
