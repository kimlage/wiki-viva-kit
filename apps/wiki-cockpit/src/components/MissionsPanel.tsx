// MissionsPanel: honest gamification. Every mission is derived from the REAL
// wiki state (stale pages, missing freshness data, unsourced content, changes
// waiting at the human gate) and clears itself when the wiki improves. The
// reward layer is the kit's karma system — append-only events, badges and
// journey levels with anti-gaming rules and no person-vs-person ranking —
// plus context vitality. No XP is fabricated in the UI.

import { useMemo } from "react";
import { Sparkles } from "lucide-react";
import { t, uiLanguage } from "../data/i18n";
import { contextLabel, isRawData, pageTypeStyle, trustColor } from "../data/presentation";
import { composeInstruments } from "../data/surfaces";
import type { BriefSpec, PageRecord, SnapshotBundle } from "../types";
import { HelpTip } from "./HelpTip";

export type Mission = {
  key: string;
  kind: "refresh" | "verify" | "evidence" | "approve";
  title: string;
  why: string;
  pageId?: string;
  href?: string;
};

const DIMENSION_LABELS: Record<string, { en: string; pt: string }> = {
  clareza: { en: "clarity", pt: "clareza" },
  confiabilidade: { en: "reliability", pt: "confiabilidade" },
  cuidado: { en: "care", pt: "cuidado" },
  stewardship: { en: "stewardship", pt: "stewardship" },
  conexao: { en: "connection", pt: "conexão" },
  aprendizado: { en: "learning", pt: "aprendizado" },
  acao: { en: "action", pt: "ação" },
  inspiracao: { en: "inspiration", pt: "inspiração" }
};

function overdueDays(page: PageRecord, generatedAt: string): number {
  const updated = Date.parse(page.updated_at ? `${page.updated_at.slice(0, 10)}T00:00:00Z` : "");
  const now = Date.parse(generatedAt);
  const budget = Number.parseFloat(page.stale_after_days || "90") || 90;
  if (!Number.isFinite(updated) || !Number.isFinite(now)) return 0;
  return Math.max(0, Math.round((now - updated) / 86400000 - budget));
}

export function deriveMissions(bundle: SnapshotBundle, demo: boolean): Mission[] {
  const missions: Mission[] = [];
  // Missions are the gamification PACKAGE, not a platform behavior: without
  // ui_missions on the root stack the world is quiet — data still derives
  // (BlocksDock shows it) but nothing asks for attention. Providers govern
  // which transformations run.
  const instruments = composeInstruments(bundle);
  if (!instruments.missionsEnabled) return missions;
  const providers = new Set(instruments.missionProviders);
  const generatedAt = bundle.manifest.generated_at;
  const pages = bundle.pages.pages;

  if (providers.has("stale")) {
    [...pages]
      .filter((page) => page.freshness_state === "stale")
      .sort((a, b) => overdueDays(b, generatedAt) - overdueDays(a, generatedAt) || a.title.localeCompare(b.title))
      .slice(0, 5)
      .forEach((page) => {
        missions.push({
          key: `refresh-${page.id}`,
          kind: "refresh",
          title: t("missions.refresh.title", { title: page.title }),
          why: t("missions.refresh.why", { days: overdueDays(page, generatedAt) }),
          pageId: page.id
        });
      });
  }

  [...pages]
    .filter((page) => page.freshness_state === "unknown" && !isRawData(page.page_type))
    .sort((a, b) => a.title.localeCompare(b.title))
    .slice(0, 4)
    .forEach((page) => {
      missions.push({
        key: `verify-${page.id}`,
        kind: "verify",
        title: t("missions.verify.title", { title: page.title }),
        why: t("missions.verify.why"),
        pageId: page.id
      });
    });

  [...pages]
    .filter(
      (page) =>
        page.source_refs.length === 0 &&
        !isRawData(page.page_type) &&
        ["content", "decision"].includes(pageTypeStyle(page.page_type).family)
    )
    .sort((a, b) => a.title.localeCompare(b.title))
    .slice(0, 4)
    .forEach((page) => {
      missions.push({
        key: `evidence-${page.id}`,
        kind: "evidence",
        title: t("missions.evidence.title", { title: page.title }),
        why: t("missions.evidence.why"),
        pageId: page.id
      });
    });

  // Block-derived missions: the relations module (cared-for network) and empty
  // required quadrants. Deduped across anchors — a person can be in the root's
  // and an area's scope. These use the amber "refresh" kind: a relation past its
  // cadence genuinely "needs refresh", the same honest signal as a stale page.
  const anchors = bundle.blockStacks?.anchors ?? {};
  const seenRel = new Set<string>();
  const dueRows: { person: string; title: string; overdue: number }[] = [];
  const upRows: { person: string; title: string; kind: string; days: number }[] = [];
  const commitRows: { person: string; title: string; ref: string; days: number }[] = [];
  for (const record of Object.values(anchors)) {
    const rel = record.derived?.relations;
    if (!rel) continue;
    for (const r of rel.due) if (!seenRel.has(`due-${r.person}`)) { seenRel.add(`due-${r.person}`); dueRows.push({ person: r.person, title: r.title, overdue: r.overdue_days }); }
    for (const r of rel.upcoming_dates) if (!seenRel.has(`up-${r.person}`)) { seenRel.add(`up-${r.person}`); upRows.push({ person: r.person, title: r.title, kind: r.kind, days: r.in_days }); }
    for (const r of rel.open_commitments) if (!seenRel.has(`c-${r.person}`)) { seenRel.add(`c-${r.person}`); commitRows.push({ person: r.person, title: r.title, ref: r.ref, days: r.days_left }); }
  }
  if (providers.has("relation_cadence_overdue")) {
    dueRows.sort((a, b) => b.overdue - a.overdue).slice(0, 3).forEach((r) => {
      missions.push({ key: `relation-${r.person}`, kind: "refresh", title: t("missions.relation.title", { title: r.title }), why: t("missions.relation.why", { n: r.overdue }), pageId: r.person });
    });
  }
  if (providers.has("date_upcoming")) {
    upRows.sort((a, b) => a.days - b.days).slice(0, 2).forEach((r) => {
      missions.push({ key: `date-${r.person}`, kind: "verify", title: t("missions.date.title", { title: r.title, kind: r.kind }), why: t("missions.date.why", { n: r.days }), pageId: r.person });
    });
  }
  if (providers.has("commitment_open")) {
    commitRows.sort((a, b) => a.days - b.days).slice(0, 2).forEach((r) => {
      missions.push({ key: `commit-${r.person}`, kind: "verify", title: t("missions.commitment.title", { title: r.title }), why: t("missions.commitment.why", { n: r.days }), pageId: r.person });
    });
  }

  const changed = bundle.git.worktree.changed_files.length;
  if (changed > 0 && providers.has("approvals_pending")) {
    missions.push({
      key: "approve-changes",
      kind: "approve",
      title: t("missions.approve.title", { n: changed }),
      why: t("missions.approve.why"),
      href: demo ? "/demo/review" : "/review"
    });
  }
  return missions;
}

// Map a mission to a work-brief spec: refresh/verify/evidence ground in the
// page and seed the intent from the mission's own "why"; approve is the human
// gate and never gets a brief.
export function missionBriefSpec(mission: Mission): BriefSpec | null {
  if (!mission.pageId) return null;
  const kind = mission.kind === "verify" ? "verify" : mission.kind === "evidence" ? "evidence" : "refresh";
  return {
    mission_kind: kind,
    theme: `${mission.kind}-${mission.pageId}`,
    grounding: { page_ids: [mission.pageId] },
    intent: mission.why
  };
}

function ProgressBar({ value, max, tone }: { value: number; max: number; tone: string }) {
  const ratio = max > 0 ? Math.min(value / max, 1) : 0;
  return (
    <span className="missionBar" aria-hidden>
      <i style={{ width: `${Math.round(ratio * 100)}%`, background: tone }} />
    </span>
  );
}

export function MissionsPanel({
  bundle,
  demo,
  onOpenPage,
  onComposeBrief,
  onClose
}: {
  bundle: SnapshotBundle;
  demo: boolean;
  onOpenPage: (id: string) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  onClose: () => void;
}) {
  const language = uiLanguage();
  const missions = useMemo(() => deriveMissions(bundle, demo), [bundle, demo]);
  const pages = bundle.pages.pages;
  const fresh = pages.filter((page) => page.freshness_state === "fresh").length;
  const evidenced = pages.filter((page) => page.source_refs.length > 0).length;
  const recentWins = bundle.timeline.bands.last_7_days || 0;
  const score = bundle.score;
  const vitality = Object.values(score?.vitality ?? {}).sort((a, b) => a.context.localeCompare(b.context));

  return (
    <div className="missionsPanel" role="region" aria-label={t("missions.aria")}>
      <header>
        <strong>{t("missions.title")}</strong>
        <HelpTip title={t("missions.title")} body={t("missions.karmaHelp")} />
        <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
          ×
        </button>
      </header>
      <p className="missionsIntro">{t("missions.intro")}</p>

      {onComposeBrief && missions.length > 0 && (
        <div className="missionsBriefTopRow">
          <button
            className="secondaryButton missionsBriefTop"
            onClick={() =>
              onComposeBrief({
                mission_kind: "state",
                theme: "top-problems",
                grounding: { state_report: { scope: "missions", limit: 6 } }
              })
            }
            type="button"
          >
            <Sparkles size={14} />
            <span>{t("missions.brief.top")}</span>
          </button>
          <HelpTip title={t("missions.brief.generate")} body={t("missions.brief.help")} />
        </div>
      )}

      <div className="missionsProgress" aria-label={t("missions.title")}>
        <div className="missionStat">
          <span>
            {t("missions.freshness")} <HelpTip term="freshness" />
          </span>
          <ProgressBar value={fresh} max={pages.length} tone={trustColor("fresh")} />
          <small>{t("missions.freshnessDetail", { fresh, total: pages.length })}</small>
        </div>
        <div className="missionStat">
          <span>
            {t("missions.evidence")} <HelpTip term="evidence" />
          </span>
          <ProgressBar value={evidenced} max={pages.length} tone="#57d9a0" />
          <small>{t("missions.evidenceDetail", { n: evidenced })}</small>
        </div>
        <div className="missionStat">
          <span>{t("missions.recentWins")}</span>
          <ProgressBar value={Math.min(recentWins, 20)} max={20} tone={trustColor("root")} />
          <small>{t("missions.recentWinsDetail", { n: recentWins })}</small>
        </div>
      </div>

      <div className="missionList">
        {missions.map((mission) => (
          <article className={`missionItem kind-${mission.kind}`} key={mission.key}>
            <div>
              <strong>{mission.title}</strong>
              <small>{mission.why}</small>
            </div>
            {mission.pageId && (
              <div className="missionActions">
                <button className="textButton" onClick={() => onOpenPage(mission.pageId!)} type="button">
                  {t("missions.open")}
                </button>
                {onComposeBrief && (
                  <button
                    className="textButton missionBriefButton"
                    onClick={() => {
                      const spec = missionBriefSpec(mission);
                      if (spec) onComposeBrief(spec);
                    }}
                    type="button"
                  >
                    {t("missions.brief.generate")}
                  </button>
                )}
              </div>
            )}
            {mission.href && (
              <a className="textButton" href={mission.href}>
                {t("missions.open")}
              </a>
            )}
          </article>
        ))}
        {missions.length === 0 && <p className="missionsEmpty">{t("missions.empty")}</p>}
      </div>

      {score?.enabled ? (
        <div className="missionsKarma">
          <div className="karmaHead">
            <span>{t("missions.karmaLevel")}</span>
            <strong>{score.level_labels?.[language] || score.level_labels?.en || score.level || "—"}</strong>
            <small>{t("missions.karmaTotal", { n: Math.round(score.total) })}</small>
          </div>
          <div className="karmaDimensions">
            {Object.entries(score.by_dimension)
              .filter(([, value]) => value > 0)
              .sort(([, a], [, b]) => b - a)
              .map(([dimension, value]) => (
                <span className="karmaDimension" key={dimension}>
                  {DIMENSION_LABELS[dimension]?.[language] || dimension} · {value.toFixed(1)}
                </span>
              ))}
          </div>
          <div className="karmaBadges">
            <span>{t("missions.badges")}</span>
            {score.badges.length > 0 ? (
              score.badges.map((badge) => (
                <span
                  className="pill pill-info"
                  key={badge.id}
                  title={(language === "pt" ? badge.criterion_pt : badge.criterion_en) || badge.id}
                >
                  🏅 {language === "pt" ? badge.pt : badge.en}
                </span>
              ))
            ) : (
              <small>{t("missions.noBadges")}</small>
            )}
          </div>
          {vitality.length > 0 && (
            <div className="karmaVitality">
              <span>
                {t("missions.vitality")} <HelpTip term="vitality" />
              </span>
              {vitality.map((item) => (
                <div className="vitalityRow" key={item.context}>
                  <small>{contextLabel(item.context)}</small>
                  <ProgressBar value={item.indice_vitalidade} max={100} tone={trustColor("root")} />
                  <small>{Math.round(item.indice_vitalidade)}</small>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <p className="missionsKarmaOff">{t("missions.karmaOff")}</p>
      )}
    </div>
  );
}
