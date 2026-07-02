// MissionsPanel: honest gamification. Every mission is derived from the REAL
// wiki state (stale pages, missing freshness data, unsourced content, changes
// waiting at the human gate) and clears itself when the wiki improves. The
// reward layer is the kit's karma system — append-only events, badges and
// journey levels with anti-gaming rules and no person-vs-person ranking —
// plus context vitality. No XP is fabricated in the UI.

import { useMemo } from "react";
import { t, uiLanguage } from "../data/i18n";
import { contextLabel, isRawData, pageTypeStyle, trustColor } from "../data/presentation";
import type { PageRecord, SnapshotBundle } from "../types";
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
  const generatedAt = bundle.manifest.generated_at;
  const pages = bundle.pages.pages;

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

  const changed = bundle.git.worktree.changed_files.length;
  if (changed > 0) {
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
  onClose
}: {
  bundle: SnapshotBundle;
  demo: boolean;
  onOpenPage: (id: string) => void;
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
              <button className="textButton" onClick={() => onOpenPage(mission.pageId!)} type="button">
                {t("missions.open")}
              </button>
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
