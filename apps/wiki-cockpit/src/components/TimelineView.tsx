import {
  Activity,
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  Clock3,
  Database,
  FileText,
  GitCommitHorizontal,
  ListTodo,
  Scale,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { t, uiLanguage } from "../data/i18n";
import { experiencePackLabel, humanizePackIdentifier } from "../data/experiencePacks";
import {
  TEMPORAL_LANE_IDS,
  filterTemporalEvents,
  firstTemporalPageId,
  pageIdFromTemporalRef,
  temporalDisplayEntries,
  temporalLane,
  temporalValueForMode
} from "../data/temporalPresentation";
import type { TemporalLaneId, TemporalTimeMode } from "../data/temporalPresentation";
import type { WorldPatch, WorldQuery } from "../router";
import type { ExperiencePackComposition, ExperiencePackSlot, PageRecord, TemporalEvent, TemporalGraphPayload } from "../types";
import "./timeline.css";

type TemporalQuery = Pick<
  WorldQuery,
  "timeFrom" | "timeTo" | "timeCursor" | "timeMode" | "timeLanes" | "compareRevision"
>;

export type TimelineViewProps = {
  payload: TemporalGraphPayload;
  pages: PageRecord[];
  query: TemporalQuery;
  inactive?: boolean;
  experiencePacks?: ExperiencePackComposition;
  packTimelineProfiles?: ExperiencePackSlot[];
  onQueryChange: (patch: WorldPatch) => void;
  onOpenPage: (pageId: string) => void;
};

const INITIAL_VISIBLE_EVENTS = 80;

const LANE_ICONS: Readonly<Record<TemporalLaneId, LucideIcon>> = {
  source: Database,
  action: ListTodo,
  decision: Scale,
  receipt: CheckCircle2,
  page: FileText,
  system: GitCommitHorizontal,
  other: CircleHelp
};

function normalizedMode(value: WorldQuery["timeMode"]): TemporalTimeMode {
  if (value === "occurred" || value === "recorded") return value;
  return "event";
}

function readableKind(kind: string, experiencePacks?: ExperiencePackComposition): string {
  const key = `timeline.kind.${kind}`;
  const localized = t(key);
  return localized === key ? experiencePackLabel(experiencePacks, kind) : localized;
}

function temporalLabel(value: string | null | undefined, precision?: string): string {
  if (!value) return t("timeline.time.missing");
  const locale = uiLanguage() === "pt" ? "pt-BR" : "en-US";
  if (/^\d{4}$/.test(value)) return `${value} · ${t("timeline.precision.year")}`;
  if (/^\d{4}-\d{2}$/.test(value)) {
    const [year, month] = value.split("-").map(Number);
    return `${new Intl.DateTimeFormat(locale, { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, 1)))} · ${t("timeline.precision.month")}`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return `${new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`))} · ${t("timeline.precision.day")}`;
  }
  const instant = Date.parse(value);
  if (!Number.isFinite(instant)) return value;
  const label = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC"
  }).format(new Date(instant));
  const technical = /T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  const exactSuffix = technical?.[1]
    ? `${technical[1]}${technical[2]}`
    : "UTC";
  return precision === "instant" ? `${label} · ${exactSuffix}` : `${label} · ${exactSuffix} · ${precision || t("timeline.precision.instant")}`;
}

function pageForRef(ref: string, pageByRef: ReadonlyMap<string, PageRecord>): PageRecord | undefined {
  const pageId = pageIdFromTemporalRef(ref);
  return pageId ? pageByRef.get(pageId) : undefined;
}

function eventTitle(
  event: TemporalEvent,
  pageByRef: ReadonlyMap<string, PageRecord>,
  experiencePacks?: ExperiencePackComposition
): string {
  for (const ref of event.subject_refs) {
    const page = pageForRef(ref, pageByRef);
    if (page) return page.title;
  }
  return readableKind(event.kind, experiencePacks);
}

function eventContext(event: TemporalEvent): string {
  return event.context_refs[0]?.replace(/^context:/, "") || t("timeline.context.system");
}

function temporalFieldLabel(field: string): string {
  const key = `timeline.field.${field}`;
  const localized = t(key);
  return localized === key ? field.replaceAll("_", " ") : localized;
}

type SafeTemporalDiagnostic = {
  code: string;
  adapter: string;
  subjectRef: string;
  errorCodes: string[];
};

function safeTemporalDiagnostics(payload: TemporalGraphPayload): SafeTemporalDiagnostic[] {
  return payload.diagnostics.slice(0, 20).map((diagnostic) => ({
    code: typeof diagnostic.code === "string" ? diagnostic.code : "temporal_adapter_diagnostic",
    adapter: typeof diagnostic.adapter === "string" ? diagnostic.adapter : "unknown_adapter",
    subjectRef: typeof diagnostic.subject_ref === "string" ? diagnostic.subject_ref : "unknown_subject",
    errorCodes: Array.isArray(diagnostic.error_codes)
      ? diagnostic.error_codes.filter((value): value is string => typeof value === "string").slice(0, 12)
      : []
  }));
}

function DateFact({
  label,
  value,
  precision
}: {
  label: string;
  value: string | null;
  precision?: string;
}) {
  return (
    <div className={value ? "timelineFact" : "timelineFact missing"}>
      <dt>{label}</dt>
      <dd title={value || undefined}>{temporalLabel(value, precision)}</dd>
    </div>
  );
}

function StateTable({ title, value }: { title: string; value: Record<string, unknown> }) {
  const entries = temporalDisplayEntries(value);
  return (
    <section className="timelineStatePanel">
      <h4>{title}</h4>
      {entries.length ? (
        <dl>
          {entries.map(([key, item]) => (
            <div key={key}>
              <dt>{key.replaceAll("_", " ")}</dt>
              <dd>{item}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>{t("timeline.state.empty")}</p>
      )}
    </section>
  );
}

export function TimelineView({
  payload,
  pages,
  query,
  inactive = false,
  experiencePacks,
  packTimelineProfiles = [],
  onQueryChange,
  onOpenPage
}: TimelineViewProps) {
  const mode = normalizedMode(query.timeMode);
  const filterSignature = [mode, query.timeFrom, query.timeTo, [...query.timeLanes].sort().join(",")].join("|");
  const [visibleWindow, setVisibleWindow] = useState(() => ({ signature: filterSignature, limit: INITIAL_VISIBLE_EVENTS }));
  const visibleLimit = visibleWindow.signature === filterSignature ? visibleWindow.limit : INITIAL_VISIBLE_EVENTS;
  const eventButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const inspectorRef = useRef<HTMLElement>(null);
  const inspectorHeadingRef = useRef<HTMLHeadingElement>(null);
  const pageByRef = useMemo(() => {
    const index = new Map<string, PageRecord>();
    pages.forEach((page) => {
      index.set(page.id, page);
      index.set(page.path, page);
    });
    return index;
  }, [pages]);
  const laneCounts = useMemo(() => {
    const counts = Object.fromEntries(TEMPORAL_LANE_IDS.map((lane) => [lane, 0])) as Record<TemporalLaneId, number>;
    payload.events.forEach((event) => { counts[temporalLane(event)] += 1; });
    return counts;
  }, [payload.events]);
  const invalidRange = Boolean(query.timeFrom && query.timeTo && query.timeFrom > query.timeTo);
  const filteredEvents = useMemo(
    () => invalidRange ? [] : filterTemporalEvents(payload.events, {
      mode,
      from: query.timeFrom,
      to: query.timeTo,
      lanes: query.timeLanes
    }),
    [invalidRange, mode, payload.events, query.timeFrom, query.timeLanes, query.timeTo]
  );
  const selectedIndex = filteredEvents.findIndex((event) => event.event_id === query.timeCursor);
  const renderedEvents = filteredEvents.slice(0, visibleLimit);
  const selectedEvent = selectedIndex >= 0 ? filteredEvents[selectedIndex] : null;
  const selectedRendered = Boolean(selectedEvent && renderedEvents.some((event) => event.event_id === selectedEvent.event_id));
  const selectedPageId = selectedEvent ? firstTemporalPageId(selectedEvent) : null;
  const staleCursor = Boolean(query.timeCursor && !selectedEvent);
  const modeDatedCount = useMemo(
    () => payload.events.filter((event) => Boolean(temporalValueForMode(event, mode))).length,
    [mode, payload.events]
  );
  const diagnostics = useMemo(() => safeTemporalDiagnostics(payload), [payload]);

  const toggleLane = (lane: TemporalLaneId) => {
    const selected = new Set(query.timeLanes);
    if (selected.has(lane)) selected.delete(lane);
    else selected.add(lane);
    onQueryChange({
      timeLanes: TEMPORAL_LANE_IDS.filter((candidate) => selected.has(candidate)),
      timeCursor: null
    });
  };

  const selectEvent = (eventId: string, revealInspector = false) => {
    onQueryChange({ timeCursor: eventId });
    if (!revealInspector || typeof window === "undefined" || !window.matchMedia?.("(max-width: 980px)").matches) return;
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      inspectorRef.current?.scrollIntoView({ block: "start" });
      inspectorHeadingRef.current?.focus({ preventScroll: true });
    }));
  };

  const moveEventFocus = (eventId: string, key: string) => {
    const currentIndex = renderedEvents.findIndex((event) => event.event_id === eventId);
    if (currentIndex < 0) return false;
    const nextIndex = key === "Home"
      ? 0
      : key === "End"
        ? renderedEvents.length - 1
        : Math.max(0, Math.min(renderedEvents.length - 1, currentIndex + (key === "ArrowUp" ? -1 : 1)));
    const next = renderedEvents[nextIndex];
    if (!next) return false;
    selectEvent(next.event_id);
    window.requestAnimationFrame(() => eventButtonRefs.current.get(next.event_id)?.focus({ preventScroll: false }));
    return true;
  };

  const contractWarning =
    payload.returned_count !== payload.events.length ||
    payload.event_count !== payload.total_count ||
    payload.summary.event_count !== payload.total_count ||
    payload.truncated;

  return (
    <section
      className="timelineSurface"
      aria-labelledby="timeline-heading"
      aria-hidden={inactive || undefined}
      data-temporal-mode={mode}
      ref={(target) => {
        if (target) target.inert = inactive;
      }}
    >
      <header className="timelineHeader">
        <div>
          <span className="timelineEyebrow"><Clock3 size={15} aria-hidden="true" /> {t("timeline.eyebrow")}</span>
          <h2 id="timeline-heading">{t("timeline.title")}</h2>
          <p>{t("timeline.intro")}</p>
        </div>
        <dl className="timelineSummary" aria-label={t("timeline.summary.aria")}>
          <div><dt>{t("timeline.summary.events")}</dt><dd>{payload.total_count}</dd></div>
          <div><dt>{t("timeline.summary.dated")}</dt><dd>{modeDatedCount}</dd></div>
          <div><dt>{t("timeline.summary.imprecise")}</dt><dd>{payload.summary.imprecise_count}</dd></div>
          <div><dt>{t("timeline.summary.conflicts")}</dt><dd>{payload.summary.conflict_count}</dd></div>
          <div><dt>{t("timeline.summary.diagnostics")}</dt><dd>{payload.summary.diagnostic_count}</dd></div>
        </dl>
      </header>

      <div className="timelineNotices">
        {contractWarning && (
          <div className="timelineContractWarning" role="alert">
            <AlertTriangle size={17} aria-hidden="true" />
            <span>{t("timeline.contract.partial", { returned: payload.returned_count, total: payload.total_count })}</span>
          </div>
        )}
        {payload.summary.diagnostic_count > 0 && (
          <details className="timelineDiagnosticWarning">
            <summary>
              <AlertTriangle size={17} aria-hidden="true" />
              {t("timeline.diagnostics.summary", { count: payload.summary.diagnostic_count })}
            </summary>
            <p>{t("timeline.diagnostics.body", { shown: diagnostics.length, total: payload.summary.diagnostic_count })}</p>
            <ul>
              {diagnostics.map((diagnostic, index) => (
                <li key={`${diagnostic.code}-${diagnostic.subjectRef}-${index}`}>
                  <code>{diagnostic.code}</code>
                  <span>{diagnostic.adapter} · {diagnostic.subjectRef}</span>
                  {diagnostic.errorCodes.length > 0 && <small>{diagnostic.errorCodes.join(", ")}</small>}
                </li>
              ))}
            </ul>
          </details>
        )}
        {invalidRange && (
          <div className="timelineContractWarning" role="alert">
            <AlertTriangle size={17} aria-hidden="true" />
            <span>{t("timeline.range.invalid")}</span>
          </div>
        )}
        {query.compareRevision && (
          <div className="timelineComparisonNotice" role="note">
            <GitCommitHorizontal size={17} aria-hidden="true" />
            <span>{t("timeline.compare.unavailable", { revision: query.compareRevision })}</span>
          </div>
        )}
        {packTimelineProfiles.length > 0 && (
          <details className="timelinePackProfiles">
            <summary>{t("timeline.packProfiles.summary", { count: packTimelineProfiles.length })}</summary>
            <p>{t("timeline.packProfiles.body")}</p>
            <ul>
              {packTimelineProfiles.map((profile) => (
                <li key={`${profile.pack}-${profile.slot}-${profile.contribution}`}>
                  <span title={profile.contribution}>{experiencePackLabel(experiencePacks, profile.contribution, profile.pack)}</span>
                  <small title={profile.slot}>{humanizePackIdentifier(profile.slot)}</small>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="timelineControls" role="group" aria-label={t("timeline.controls.aria")}>
        <div className="timelineModeControl" role="group" aria-label={t("timeline.mode.aria")}>
          {(["event", "occurred", "recorded"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={mode === option}
              className={mode === option ? "active" : ""}
              onClick={() => onQueryChange({ timeMode: option, timeCursor: null })}
            >
              {t(`timeline.mode.${option}`)}
            </button>
          ))}
        </div>
        <label>
          <span>{t("timeline.range.from")}</span>
          <input
            type="date"
            value={query.timeFrom.slice(0, 10)}
            onChange={(event) => onQueryChange({ timeFrom: event.currentTarget.value, timeCursor: null })}
          />
        </label>
        <label>
          <span>{t("timeline.range.to")}</span>
          <input
            type="date"
            value={query.timeTo.slice(0, 10)}
            onChange={(event) => onQueryChange({ timeTo: event.currentTarget.value, timeCursor: null })}
          />
        </label>
        <button
          className="timelineClear"
          type="button"
          onClick={() => onQueryChange({
            timeFrom: null,
            timeTo: null,
            timeCursor: null,
            timeLanes: [],
            compareRevision: null
          })}
        >
          <X size={15} aria-hidden="true" /> {t("timeline.clear")}
        </button>
      </div>

      <div className="timelineLaneControls" role="group" aria-label={t("timeline.lanes.aria")}>
        <button
          type="button"
          aria-pressed={query.timeLanes.length === 0}
          className={query.timeLanes.length === 0 ? "active" : ""}
          onClick={() => onQueryChange({ timeLanes: [], timeCursor: null })}
        >
          <Activity size={15} aria-hidden="true" />
          <span>{t("timeline.lane.all")}</span>
          <strong aria-label={t("timeline.lane.loaded", { loaded: payload.events.length, total: payload.total_count })}>
            {payload.events.length === payload.total_count ? payload.total_count : `${payload.events.length}/${payload.total_count}`}
          </strong>
        </button>
        {TEMPORAL_LANE_IDS.map((lane) => {
          const Icon = LANE_ICONS[lane];
          const active = query.timeLanes.includes(lane);
          return (
            <button
              key={lane}
              type="button"
              aria-pressed={active}
              className={active ? "active" : ""}
              onClick={() => toggleLane(lane)}
            >
              <Icon size={15} aria-hidden="true" />
              <span>{t(`timeline.lane.${lane}`)}</span>
              <strong>{laneCounts[lane]}</strong>
            </button>
          );
        })}
      </div>

      <div className="visuallyHidden" aria-live="polite" role="status">
        {selectedEvent
          ? t("timeline.inspector.announcement", {
              title: eventTitle(selectedEvent, pageByRef, experiencePacks),
              lane: t(`timeline.lane.${temporalLane(selectedEvent)}`)
            })
          : staleCursor
            ? t("timeline.inspector.stale")
            : ""}
      </div>

      <div className="timelineBody">
        <section className="timelineEventList" aria-labelledby="timeline-results-heading">
          <header>
            <div>
              <h3 id="timeline-results-heading">{t("timeline.results")}</h3>
              <p aria-live="polite">{t("timeline.results.count", { shown: renderedEvents.length, filtered: filteredEvents.length, total: payload.total_count })}</p>
            </div>
            <span>{t(`timeline.mode.${mode}Hint`)}</span>
          </header>
          {selectedEvent && !selectedRendered && (
            <p className="timelineWindowNotice" role="status">{t("timeline.window.selectedOutside")}</p>
          )}
          {invalidRange ? (
            <div className="timelineEmpty" role="note">
              <AlertTriangle size={22} aria-hidden="true" />
              <strong>{t("timeline.range.invalidTitle")}</strong>
              <p>{t("timeline.range.invalidBody")}</p>
            </div>
          ) : renderedEvents.length ? (
            <ol aria-label={t("timeline.results")}>
              {renderedEvents.map((event) => {
                const lane = temporalLane(event);
                const Icon = LANE_ICONS[lane];
                const timestamp = temporalValueForMode(event, mode);
                const timestampPrecision = mode === "event"
                  ? event.anchor?.precision
                  : mode === "recorded"
                    ? event.precision.recorded_at
                    : event.precision.occurred_at;
                const selected = selectedEvent?.event_id === event.event_id;
                const keyboardTarget = selected || (!selectedRendered && renderedEvents[0]?.event_id === event.event_id);
                return (
                  <li key={event.event_id} data-temporal-lane={lane}>
                    <button
                      type="button"
                      className={selected ? "timelineEvent active" : "timelineEvent"}
                      aria-current={selected ? "true" : undefined}
                      aria-controls="timeline-inspector"
                      tabIndex={keyboardTarget ? 0 : -1}
                      ref={(target) => {
                        if (target) eventButtonRefs.current.set(event.event_id, target);
                        else eventButtonRefs.current.delete(event.event_id);
                      }}
                      onKeyDown={(keyboardEvent) => {
                        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(keyboardEvent.key)) return;
                        keyboardEvent.preventDefault();
                        moveEventFocus(event.event_id, keyboardEvent.key);
                      }}
                      onClick={(clickEvent) => selectEvent(event.event_id, clickEvent.detail > 0)}
                    >
                      <span className="timelineEventMark"><Icon size={16} aria-hidden="true" /></span>
                      <span className="timelineEventTime" title={timestamp || undefined}>{temporalLabel(timestamp, timestampPrecision)}</span>
                      <span className="timelineEventCopy">
                        <strong>{eventTitle(event, pageByRef, experiencePacks)}</strong>
                        <small>
                          {mode === "event" && event.anchor ? `${temporalFieldLabel(event.anchor.field)} · ` : ""}
                          {readableKind(event.kind, experiencePacks)} · {eventContext(event)}
                        </small>
                      </span>
                      <span className={`timelineConfidence confidence-${event.confidence}`}>
                        {event.temporal_conflicts.length ? <AlertTriangle size={13} aria-hidden="true" /> : null}
                        {t(`timeline.confidence.${event.confidence}`)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : (
            <div className="timelineEmpty">
              <Clock3 size={22} aria-hidden="true" />
              <strong>{t("timeline.empty.title")}</strong>
              <p>{t("timeline.empty.body")}</p>
            </div>
          )}
          {renderedEvents.length < filteredEvents.length && (
            <button
              className="timelineShowMore"
              type="button"
              onClick={() => setVisibleWindow((current) => ({
                signature: filterSignature,
                limit: (current.signature === filterSignature ? current.limit : INITIAL_VISIBLE_EVENTS) + INITIAL_VISIBLE_EVENTS
              }))}
            >
              {t("timeline.showMore", { remaining: filteredEvents.length - renderedEvents.length })}
            </button>
          )}
        </section>

        <aside
          id="timeline-inspector"
          ref={inspectorRef}
          className="timelineInspector"
          aria-label={t("timeline.inspector.aria")}
        >
          {selectedEvent ? (
            <>
              <header>
                <span>{t(`timeline.lane.${temporalLane(selectedEvent)}`)}</span>
                <h3 ref={inspectorHeadingRef} tabIndex={-1}>{eventTitle(selectedEvent, pageByRef, experiencePacks)}</h3>
                <p>{readableKind(selectedEvent.kind, experiencePacks)}</p>
                {selectedPageId && pageByRef.has(selectedPageId) && (
                  <button type="button" onClick={() => onOpenPage(selectedPageId)}>
                    <BookOpen size={15} aria-hidden="true" /> {t("timeline.openPage")}
                  </button>
                )}
              </header>
              <dl className="timelineFacts">
                <DateFact
                  label={`${t("timeline.field.anchor")} · ${selectedEvent.anchor ? temporalFieldLabel(selectedEvent.anchor.field) : t("timeline.time.missing")}`}
                  value={selectedEvent.anchor?.value ?? null}
                  precision={selectedEvent.anchor?.precision}
                />
                <DateFact label={t("timeline.field.occurred_at")} value={selectedEvent.occurred_at} precision={selectedEvent.precision.occurred_at} />
                <DateFact label={t("timeline.field.recorded_at")} value={selectedEvent.recorded_at} precision={selectedEvent.precision.recorded_at} />
                <DateFact label={t("timeline.field.created_at")} value={selectedEvent.created_at} precision={selectedEvent.precision.created_at} />
                <DateFact label={t("timeline.field.due_at")} value={selectedEvent.due_at} precision={selectedEvent.precision.due_at} />
                <DateFact label={t("timeline.field.completed_at")} value={selectedEvent.completed_at} precision={selectedEvent.precision.completed_at} />
                <DateFact label={t("timeline.field.verified_at")} value={selectedEvent.verified_at} precision={selectedEvent.precision.verified_at} />
                <DateFact label={t("timeline.field.ingested_at")} value={selectedEvent.ingested_at} precision={selectedEvent.precision.ingested_at} />
                <DateFact label={t("timeline.field.valid_from")} value={selectedEvent.valid_from} precision={selectedEvent.precision.valid_from} />
                <DateFact label={t("timeline.field.valid_to")} value={selectedEvent.valid_to} precision={selectedEvent.precision.valid_to} />
                <DateFact label={t("timeline.field.superseded_at")} value={selectedEvent.superseded_at} precision={selectedEvent.precision.superseded_at} />
              </dl>

              {(Object.keys(selectedEvent.before).length > 0 || Object.keys(selectedEvent.after).length > 0) && (
                <div className="timelineStateComparison" role="group" aria-label={t("timeline.state.aria")}>
                  <StateTable title={t("timeline.state.before")} value={selectedEvent.before} />
                  <StateTable title={t("timeline.state.after")} value={selectedEvent.after} />
                </div>
              )}

              <section className="timelineReferences">
                <h4>{t("timeline.references")}</h4>
                {[...new Set([...selectedEvent.subject_refs, ...selectedEvent.source_refs, ...selectedEvent.evidence_refs])].map((ref) => {
                  const page = pageForRef(ref, pageByRef);
                  return page ? (
                    <button key={ref} type="button" onClick={() => onOpenPage(page.id)}>
                      <FileText size={14} aria-hidden="true" /> {page.title}
                    </button>
                  ) : <code key={ref}>{ref}</code>;
                })}
              </section>

              <details className="timelineTechnical">
                <summary>{t("timeline.technical")}</summary>
                <dl>
                  <div><dt>{t("timeline.technical.id")}</dt><dd><code>{selectedEvent.event_id}</code></dd></div>
                  <div><dt>{t("timeline.technical.adapter")}</dt><dd><code>{selectedEvent.origin.adapter}</code></dd></div>
                  <div><dt>{t("timeline.technical.confidence")}</dt><dd>{t(`timeline.confidence.${selectedEvent.confidence}`)}</dd></div>
                  <div><dt>{t("timeline.technical.visibility")}</dt><dd>{selectedEvent.visibility}</dd></div>
                  <div><dt>{t("timeline.technical.actor")}</dt><dd>{selectedEvent.actor ? `${selectedEvent.actor.kind} · ${selectedEvent.actor.ref}` : t("timeline.technical.none")}</dd></div>
                  <div><dt>{t("timeline.technical.causedBy")}</dt><dd>{selectedEvent.caused_by.join(", ") || t("timeline.technical.none")}</dd></div>
                  <div><dt>{t("timeline.technical.supersedes")}</dt><dd>{selectedEvent.supersedes.join(", ") || t("timeline.technical.none")}</dd></div>
                </dl>
                {selectedEvent.temporal_conflicts.length > 0 && (
                  <ul>{selectedEvent.temporal_conflicts.map((conflict) => <li key={conflict}>{conflict.replaceAll("_", " ")}</li>)}</ul>
                )}
              </details>
            </>
          ) : staleCursor ? (
            <div className="timelineInspectorEmpty" role="status">
              <AlertTriangle size={24} aria-hidden="true" />
              <strong>{t("timeline.inspector.stale")}</strong>
              <p>{t("timeline.inspector.staleBody")}</p>
            </div>
          ) : (
            <div className="timelineInspectorEmpty">
              <Clock3 size={24} aria-hidden="true" />
              <strong>{t("timeline.inspector.empty")}</strong>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
