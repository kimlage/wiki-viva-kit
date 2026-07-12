import {
  CircleDot,
  Clock3,
  Crosshair,
  Database,
  Eye,
  Grid2X2,
  History,
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
import { useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { t } from "../../data/i18n";
import { humanizePackIdentifier } from "../../data/experiencePacks";
import type { LensId, OverlayId } from "../../world/contracts";
import type { ExperiencePackComposition, ExperiencePackSlot } from "../../types";
import {
  WORLD_EXPERIENCE_AXES,
  WORLD_EXPERIENCE_KEYS,
  WORLD_OVERLAY_EXPERIENCES,
  WORLD_QUADRANT_LENS_EXPERIENCES,
  WORLD_VIEW_EXPERIENCES,
  activeQuadrantLensOption,
  isWorldOverlayId,
  registeredWorldOverlayExperiences,
  registeredWorldViewExperiences
} from "../../world/experience";
import type {
  ExperienceIconId,
  NativeWorldViewId,
  QuadrantLensSelection
} from "../../world/experience";
import type { RegistryKernel } from "../../world/registries/RegistryKernel";
import { useSurfacePresence } from "./useSurfacePresence";

export type WorldExperienceTranslate = (key: string) => string;

export type CompatibilityViewContext = {
  id: string;
  label: string;
  hint: string;
};

export type WorldNavigatorProps = {
  view?: NativeWorldViewId | null;
  compatibilityView?: CompatibilityViewContext;
  overlay: OverlayId;
  lens?: LensId | null;
  overlayResolving?: boolean;
  unavailableViews?: readonly NativeWorldViewId[];
  lensAvailable?: boolean;
  overlayAvailable?: boolean;
  registryKernel?: Pick<RegistryKernel, "views" | "overlays">;
  experiencePacks?: ExperiencePackComposition;
  activePackView?: string;
  expanded?: boolean;
  defaultExpanded?: boolean;
  panelId?: string;
  translate?: WorldExperienceTranslate;
  onExpandedChange?: (expanded: boolean) => void;
  onViewChange: (view: NativeWorldViewId) => void;
  onOverlayChange: (overlay: OverlayId) => void;
  onLensChange: (lens: QuadrantLensSelection) => void;
  onPackViewChange?: (contribution: string) => void;
};

const ICONS: Readonly<Record<ExperienceIconId, LucideIcon>> = {
  view: Eye,
  lens: Crosshair,
  overlay: Layers3,
  quadrants: Grid2X2,
  radar: Radar,
  sources: Database,
  work: ListTodo,
  timeline: History,
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
  compatibilityView,
  overlay,
  lens,
  overlayResolving = false,
  unavailableViews = [],
  lensAvailable = true,
  overlayAvailable = true,
  registryKernel,
  experiencePacks,
  activePackView,
  expanded,
  defaultExpanded = false,
  panelId,
  translate = t,
  onExpandedChange,
  onViewChange,
  onOverlayChange,
  onLensChange,
  onPackViewChange
}: WorldNavigatorProps) {
  const generatedId = useId().replaceAll(":", "");
  const resolvedPanelId = panelId || `world-experience-${generatedId}`;
  const panelHeadingId = `${resolvedPanelId}-title`;
  const unavailableViewsId = `${resolvedPanelId}-unavailable-views`;
  const learnButtonRef = useRef<HTMLButtonElement>(null);
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const isExpanded = expanded ?? internalExpanded;
  const panelPresence = useSurfacePresence(isExpanded);
  const selectedLens = activeQuadrantLensOption(lens);
  const activeCompatibilityView = view ? undefined : compatibilityView;
  const compatibilityBadge = translate(WORLD_EXPERIENCE_KEYS.compatibilityBadge);
  const compatibilitySwitchHint = translate(WORLD_EXPERIENCE_KEYS.compatibilitySwitchHint);
  const unavailableViewSet = new Set(unavailableViews);
  const activePackCount = experiencePacks?.packs.length ?? 0;
  const viewExperiences = registryKernel
    ? registeredWorldViewExperiences(registryKernel)
    : WORLD_VIEW_EXPERIENCES;
  const overlayExperiences = registryKernel
    ? registeredWorldOverlayExperiences(registryKernel)
    : WORLD_OVERLAY_EXPERIENCES;

  const packSlotGroup = (kind: keyof ExperiencePackComposition["slots"], rows: ExperiencePackSlot[]) => (
    <section className="worldNavigatorPackSlot" data-pack-slot-kind={kind}>
      <h4>{translate(`world.experience.packs.slot.${kind}`)}</h4>
      {rows.length ? (
        <ul>
          {rows.map((row) => {
            const interactiveView = kind === "views" && Boolean(onPackViewChange);
            const humanLabel = humanizePackIdentifier(row.contribution, row.pack);
            const content = (
              <>
                <strong>{humanLabel}</strong>
                <code>{row.contribution}</code>
                <small>{row.slot} · {row.mode}</small>
              </>
            );
            return (
              <li key={`${kind}-${row.pack}-${row.slot}-${row.contribution}`}>
                {interactiveView ? (
                  <button
                    type="button"
                    aria-pressed={activePackView === row.contribution}
                    aria-label={`${translate("world.experience.packs.openView")} ${humanLabel}`}
                    data-pack-view-card={row.contribution}
                    onClick={() => onPackViewChange?.(row.contribution)}
                  >
                    {content}
                  </button>
                ) : content}
              </li>
            );
          })}
        </ul>
      ) : <p>{translate("world.experience.packs.slot.empty")}</p>}
    </section>
  );

  const changeExpanded = (next: boolean) => {
    if (expanded === undefined) setInternalExpanded(next);
    onExpandedChange?.(next);
    if (!next) queueMicrotask(() => learnButtonRef.current?.focus({ preventScroll: true }));
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
      data-world-view={view ?? activeCompatibilityView?.id ?? ""}
      data-native-view={view ?? ""}
      data-compatibility-view={activeCompatibilityView?.id ?? ""}
      data-world-overlay={overlay}
      data-world-lens={selectedLens}
    >
      <div className="worldNavigatorCompact worldRuntimeControls">
        {activeCompatibilityView && (
          <div
            className="worldNavigatorCompatibility"
            role="note"
            aria-label={`${compatibilityBadge}: ${activeCompatibilityView.label}. ${activeCompatibilityView.hint}`}
            data-compatibility-context={activeCompatibilityView.id}
            title={compatibilitySwitchHint}
          >
            <span>{compatibilityBadge}</span>
            <strong>{activeCompatibilityView.label}</strong>
            <small>{activeCompatibilityView.hint}</small>
          </div>
        )}
        <div
          className="worldNavigatorViewControls worldRuntimeControlGroup"
          role="group"
          aria-label={translate(WORLD_EXPERIENCE_KEYS.viewGroupAria)}
        >
          {viewExperiences.map((option) => (
            <button
              key={option.id}
              type="button"
              className={view === option.id ? "runtimeControl worldNavigatorView active" : "runtimeControl worldNavigatorView"}
              aria-pressed={view === option.id}
              aria-label={translate(option.labelKey)}
              aria-describedby={unavailableViewSet.has(option.id) ? unavailableViewsId : undefined}
              data-view-option={option.id}
              disabled={unavailableViewSet.has(option.id)}
              title={unavailableViewSet.has(option.id) ? translate("world.experience.capability.timelineUnavailable") : undefined}
              onClick={() => onViewChange(option.id)}
            >
              <ExperienceIcon id={option.icon} />
              <span>{translate(option.labelKey)}</span>
            </button>
          ))}
        </div>
        {unavailableViews.length > 0 && (
          <span id={unavailableViewsId} className="worldNavigatorUnavailableNote" role="note">
            {translate("world.experience.capability.timelineUnavailable")}
          </span>
        )}

        <label className="worldRuntimeSelect worldNavigatorOverlaySelect">
          <span>{translate(WORLD_EXPERIENCE_KEYS.overlaySelectLabel)}</span>
          <select
            value={overlay}
            aria-label={translate(WORLD_EXPERIENCE_KEYS.overlaySelectLabel)}
            aria-busy={overlayResolving || undefined}
            disabled={overlayResolving || !overlayAvailable}
            title={!overlayAvailable ? translate("world.experience.capability.spatialOnly") : undefined}
            onChange={(event) => {
              if (isWorldOverlayId(event.target.value)) onOverlayChange(event.target.value);
            }}
          >
            {overlayExperiences.map((option) => (
              <option key={option.id} value={option.id}>
                {translate(option.labelKey)}
              </option>
            ))}
          </select>
        </label>

        <button
          ref={learnButtonRef}
          className={isExpanded ? "runtimeControl worldNavigatorLearn active" : "runtimeControl worldNavigatorLearn"}
          type="button"
          aria-expanded={isExpanded}
          aria-controls={resolvedPanelId}
          onClick={() => changeExpanded(!isExpanded)}
        >
          <Info size={16} aria-hidden="true" focusable="false" />
          <span>{translate(WORLD_EXPERIENCE_KEYS.learn)}</span>
        </button>
        {experiencePacks && (
          <button
            type="button"
            className="worldNavigatorPackBadge"
            data-active-pack-count={activePackCount}
            aria-pressed={Boolean(activePackView)}
            title={translate(activePackCount ? "world.experience.packs.active" : "world.experience.packs.coreOnly")}
            onClick={() => changeExpanded(true)}
          >
            {translate("world.experience.packs.short")} · {activePackCount}
          </button>
        )}
      </div>

      {panelPresence.mounted && (
        <div
          id={resolvedPanelId}
          className={panelPresence.phase === "closing" ? "worldNavigatorPanel closing" : "worldNavigatorPanel"}
          role="region"
          aria-labelledby={panelHeadingId}
          aria-hidden={panelPresence.phase === "closing" ? true : undefined}
          ref={(target) => {
            if (target) target.inert = panelPresence.phase === "closing";
          }}
          data-surface-phase={panelPresence.phase}
          onKeyDown={onPanelKeyDown}
          onAnimationEnd={(event) => {
            if (panelPresence.phase === "closing" && event.currentTarget === event.target) panelPresence.completeExit();
          }}
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

          {activeCompatibilityView && (
            <aside
              className="worldNavigatorCompatibilityNotice"
              aria-label={`${compatibilityBadge}: ${activeCompatibilityView.label}`}
              data-compatibility-notice={activeCompatibilityView.id}
            >
              <span>{compatibilityBadge}</span>
              <div>
                <strong>{activeCompatibilityView.label}</strong>
                <p>{activeCompatibilityView.hint}</p>
              </div>
              <small>{compatibilitySwitchHint}</small>
            </aside>
          )}

          {(!lensAvailable || !overlayAvailable) && (
            <aside className="worldNavigatorCapabilityNotice" role="note">
              <Info size={17} aria-hidden="true" />
              <span>{translate("world.experience.capability.spatialOnly")}</span>
            </aside>
          )}

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

          <section
            className="worldNavigatorSection"
            aria-labelledby={`${resolvedPanelId}-views`}
            data-experience-section="views"
          >
            <header>
              <h3 id={`${resolvedPanelId}-views`}>{translate(WORLD_EXPERIENCE_KEYS.viewsTitle)}</h3>
              <p>{translate(WORLD_EXPERIENCE_KEYS.viewsIntro)}</p>
            </header>
            <div className="worldNavigatorCardGrid worldNavigatorViewCards">
              {viewExperiences.map((option) => {
                const descriptionId = `${resolvedPanelId}-view-${option.id}`;
                return (
                  <button
                    key={option.id}
                    className={view === option.id ? "worldNavigatorCard active" : "worldNavigatorCard"}
                    type="button"
                    aria-pressed={view === option.id}
                    aria-describedby={unavailableViewSet.has(option.id) ? `${descriptionId} ${unavailableViewsId}` : descriptionId}
                    data-view-card={option.id}
                    disabled={unavailableViewSet.has(option.id)}
                    title={unavailableViewSet.has(option.id) ? translate("world.experience.capability.timelineUnavailable") : undefined}
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

          {experiencePacks && (
            <section className="worldNavigatorSection worldNavigatorPackCatalog" data-experience-section="packs">
              <header>
                <h3>{translate("world.experience.packs.title")}</h3>
                <p>{translate("world.experience.packs.intro")}</p>
              </header>
              {experiencePacks.packs.length ? (
                <div className="worldNavigatorPackList">
                  {experiencePacks.packs.map((pack) => (
                    <span key={pack.id} data-pack-id={pack.id}>
                      <strong>{pack.id}</strong><small>v{pack.version}</small>
                    </span>
                  ))}
                </div>
              ) : <p className="worldNavigatorPackEmpty">{translate("world.experience.packs.coreOnly")}</p>}
              {experiencePacks.block_packages.length > 0 && (
                <div className="worldNavigatorBlockPackages" aria-label={translate("world.experience.packs.blockPackages")}>
                  <strong>{translate("world.experience.packs.blockPackages")}</strong>
                  {experiencePacks.block_packages.map((blockPackage) => <code key={blockPackage}>{blockPackage}</code>)}
                </div>
              )}
              <div className="worldNavigatorPackSlots">
                {packSlotGroup("views", experiencePacks.slots.views)}
                {packSlotGroup("commands", experiencePacks.slots.commands)}
                {packSlotGroup("operations", experiencePacks.slots.operations)}
                {packSlotGroup("timelines", experiencePacks.slots.timelines)}
              </div>
            </section>
          )}

          <section
            className="worldNavigatorSection"
            aria-labelledby={`${resolvedPanelId}-lenses`}
            data-experience-section="lenses"
          >
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
                    disabled={!lensAvailable}
                    onClick={() => onLensChange(option.value)}
                  >
                    <strong>{translate(option.labelKey)}</strong>
                    <small id={descriptionId}>{translate(option.descriptionKey)}</small>
                  </button>
                );
              })}
            </div>
          </section>

          <section
            className="worldNavigatorSection"
            aria-labelledby={`${resolvedPanelId}-overlays`}
            data-experience-section="overlays"
          >
            <header>
              <h3 id={`${resolvedPanelId}-overlays`}>{translate(WORLD_EXPERIENCE_KEYS.overlaysTitle)}</h3>
              <p>{translate(WORLD_EXPERIENCE_KEYS.overlaysIntro)}</p>
            </header>
            <div className="worldNavigatorCardGrid worldNavigatorOverlayCards">
              {overlayExperiences.map((option) => {
                const descriptionId = `${resolvedPanelId}-overlay-${option.id}`;
                return (
                  <button
                    key={option.id}
                    className={overlay === option.id ? "worldNavigatorCard active" : "worldNavigatorCard"}
                    type="button"
                    aria-pressed={overlay === option.id}
                    aria-describedby={descriptionId}
                    data-overlay-card={option.id}
                    disabled={overlayResolving || !overlayAvailable}
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
