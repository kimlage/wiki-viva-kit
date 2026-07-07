// SourceDock (?dock=source&src=<id>): a data source as a FIRST-CLASS entity.
// Identity (platform · locator · owner), sync health, the channels/streams as a
// table with per-stream freshness vs cadence, the executable export manual, and
// the actions: compose an ingestion brief for the stale streams (recipe becomes
// the grounding), open the config. The source page's machine sync block and the
// human recipe stay clearly separated. Everything t()'d EN+PT.

import { useMemo } from "react";
import { Database, ExternalLink, Lock, RefreshCw, X } from "lucide-react";
import { t } from "../data/i18n";
import { contextLabel } from "../data/presentation";
import { ExpandablePre } from "./ExpandablePre";
import type { BriefSpec, SnapshotBundle, SourceEntity } from "../types";

const SYNC_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  ok: "good",
  partial: "warn",
  running: "muted",
  queued: "muted",
  failed: "bad",
  never: "muted"
};

function ageLabel(days: number | null): string {
  if (days === null) return t("source.stream.never");
  if (days <= 0) return t("source.stream.today");
  return t("source.stream.daysAgo", { n: days });
}

export function SourceDock({
  bundle,
  sourceId,
  onComposeBrief,
  onNotice,
  onOpenPage,
  onOpenSource,
  onClose
}: {
  bundle: SnapshotBundle;
  sourceId: string;
  onComposeBrief?: (spec: BriefSpec) => void;
  onNotice: (text: string) => void;
  onOpenPage?: (pathOrId: string) => void;
  onOpenSource?: (id: string) => void;
  onClose: () => void;
}) {
  const sources = bundle.sourceEntities?.sources ?? [];
  const source: SourceEntity | undefined = useMemo(
    () => (sourceId ? sources.find((s) => s.source_id === sourceId) : undefined),
    [sources, sourceId]
  );

  // LIST MODE — no specific source selected: every source, sorted by attention
  // (pending streams first), each a button that drills into its detail.
  if (!sourceId) {
    const ordered = [...sources].sort(
      (a, b) => b.pending_streams - a.pending_streams || a.title.localeCompare(b.title)
    );
    const pendingTotal = sources.reduce((sum, s) => sum + s.pending_streams, 0);
    return (
      <>
        <div className="dockBackdrop" onClick={onClose} aria-hidden />
        <aside className="sourceDock worldDock" role="dialog" aria-label={t("source.list.title")}>
          <header className="dockHeader">
            <Database size={15} aria-hidden />
            <strong>{t("source.list.title", { n: sources.length })}</strong>
            <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
              <X size={16} />
            </button>
          </header>
          <p className="dockIntro">
            {t("source.list.intro")}
            {pendingTotal > 0 ? ` ${t("source.list.pending", { n: pendingTotal })}` : ""}
          </p>
          {ordered.length === 0 && <p className="dockIntro">{t("source.list.empty")}</p>}
          <ul className="sourceList">
            {ordered.map((s) => {
              const tone = SYNC_TONE[s.sync.last_status] ?? "muted";
              return (
                <li key={s.source_id}>
                  <button className="sourceListItem" onClick={() => onOpenSource?.(s.source_id)} type="button">
                    <span className="sourceListName">
                      <strong>{s.title}</strong>
                      <small>
                        <span className="sourceBadge sourceBadgeSm">{s.platform || t("source.platform.unknown")}</span>
                        {s.locator ? ` · ${s.locator}` : ""}
                      </small>
                    </span>
                    <span className="sourceListState">
                      {s.pending_streams > 0 && <span className="pill pill-warn">{t("source.list.pendingN", { n: s.pending_streams })}</span>}
                      <span className={`pill pill-${tone}`}>{t(`source.sync.${s.sync.last_status}`)}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>
      </>
    );
  }

  if (!source) {
    return (
      <>
        <div className="dockBackdrop" onClick={onClose} aria-hidden />
        <aside className="sourceDock worldDock" role="dialog" aria-label={t("source.title")}>
          <header className="dockHeader">
            <strong>{t("source.title")}</strong>
            <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
              <X size={16} />
            </button>
          </header>
          <p className="dockIntro">{t("source.notFound", { id: sourceId })}</p>
          {onOpenSource && (
            <button className="secondaryButton" onClick={() => onOpenSource("")} type="button">
              <span>{t("source.list.back")}</span>
            </button>
          )}
        </aside>
      </>
    );
  }

  const syncTone = SYNC_TONE[source.sync.last_status] ?? "muted";
  const selected = source.streams.filter((s) => s.selected);

  const composeBrief = async () => {
    if (!onComposeBrief) return;
    // Compose from the server so the recipe grounding + stale-stream targeting
    // stay authoritative (mirrors the honest gate-fix flow).
    const { composeSourceBrief } = await import("../data/snapshot");
    const result = await composeSourceBrief(source.source_id);
    if (result.ok && result.spec) {
      onComposeBrief(result.spec);
    } else {
      onNotice(t("source.brief.failed", { error: result.error ?? "?" }));
    }
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="sourceDock worldDock" role="dialog" aria-label={t("source.title")}>
        <header className="dockHeader">
          <Database size={15} aria-hidden />
          <strong>{source.title}</strong>
          <span className={`pill pill-${syncTone}`}>{t(`source.sync.${source.sync.last_status}`)}</span>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>

        <div className="sourceIdentity">
          <span className="sourceBadge">{source.platform || t("source.platform.unknown")}</span>
          {source.locator && <code className="sourceLocator">{source.locator}</code>}
          <small>
            {source.owner ? t("source.owner", { owner: source.owner }) : t("source.owner.none")}
            {source.context ? ` · ${contextLabel(source.context)}` : ""}
          </small>
        </div>

        <div className="sourceHealth" aria-label={t("source.health.aria")}>
          <span className="stripChip static">
            {t("source.health.fresh", { fresh: source.sync.streams_fresh, total: source.sync.streams_total })}
          </span>
          {source.pending_streams > 0 && (
            <span className="pill pill-warn">{t("source.health.pending", { n: source.pending_streams })}</span>
          )}
          {source.sync.last_run_at && (
            <small>
              {t("source.health.lastRun", { when: source.sync.last_run_at.replace("T", " ").slice(0, 16) })}
              {source.sync.derived_from_event ? ` · ${t("source.health.derived")}` : ""}
            </small>
          )}
          {source.schedule && source.schedule.mode !== "on_demand" && (
            <small>
              {t("source.schedule.mode." + source.schedule.mode)}
              {typeof source.next_due_days === "number"
                ? ` · ${source.next_due_days < 0 ? t("source.schedule.overdue", { n: -source.next_due_days }) : t("source.schedule.due", { n: source.next_due_days })}`
                : ""}
            </small>
          )}
        </div>

        {/* Auth is a POINTER, never a value — where the operator's credential lives. */}
        {source.auth && source.auth.method !== "none" && (
          <div className="sourceAuth" title={t("source.auth.tip")}>
            <Lock size={12} aria-hidden />
            <span>{t("source.auth.label", { method: source.auth.method })}</span>
            <code className="sourceAuthRef">{source.auth.ref}</code>
            {source.auth.scopes.length > 0 && <small>{source.auth.scopes.join(", ")}</small>}
          </div>
        )}

        {!source.recipe_ok && source.recipe_errors.length > 0 && (
          <div className="sourceRecipeError">
            <strong>{t("source.recipe.broken")}</strong>
            <ExpandablePre text={source.recipe_errors.join("\n")} title={t("source.recipe.broken")} />
          </div>
        )}

        <div className="sourceSection">
          <h4>{t("source.streams.title", { n: selected.length })}</h4>
          <table className="sourceStreams">
            <thead>
              <tr>
                <th>{t("source.streams.channel")}</th>
                <th>{t("source.streams.freshness")}</th>
                <th>{t("source.streams.privacy")}</th>
              </tr>
            </thead>
            <tbody>
              {source.streams.map((stream) => (
                <tr key={stream.id} className={stream.breached ? "streamBreached" : stream.selected ? "" : "streamSkipped"}>
                  <td>
                    <code>{stream.id}</code>
                    {!stream.selected && stream.skip_reason && <small> · {stream.skip_reason}</small>}
                  </td>
                  <td>
                    {stream.selected ? (
                      <span className={stream.breached ? "streamStale" : "streamFresh"}>
                        {ageLabel(stream.cursor_age_days)}
                        {stream.cadence_days ? ` / ${t("source.streams.cadence", { n: stream.cadence_days })}` : ""}
                      </span>
                    ) : (
                      <small>{t("source.streams.unselected")}</small>
                    )}
                  </td>
                  <td>
                    <small>{stream.privacy}</small>
                  </td>
                </tr>
              ))}
              {source.streams.length === 0 && (
                <tr>
                  <td colSpan={3}>
                    <small>{t("source.streams.none")}</small>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {source.how_to_export && (
          <details className="sourceSection sourceManual">
            <summary>{t("source.manual.title")}</summary>
            <ExpandablePre text={source.how_to_export} title={t("source.manual.title")} />
          </details>
        )}

        <div className="dockActions">
          {onComposeBrief && (
            <button
              className="btn btn--run"
              onClick={composeBrief}
              disabled={source.pending_streams === 0}
              title={source.pending_streams === 0 ? t("source.brief.upToDate") : t("source.sync.tip")}
              type="button"
            >
              <RefreshCw size={14} />
              <span>{t("source.sync.action", { n: source.pending_streams })}</span>
            </button>
          )}
          {source.config_ref && onOpenPage && (
            <button className="secondaryButton" onClick={() => onOpenPage(source.config_ref)} type="button">
              <ExternalLink size={14} />
              <span>{t("source.openConfig")}</span>
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
