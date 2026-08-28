// The guide beacon's 2D twin: the same genesis stage voice (progress, body,
// CTA, back/skip) as a fixed DOM card for fallback mode.

import { t } from "../../data/i18n";
import type { SceneGuide } from "../SystemScene";

export function GuideFallback({ guide }: { guide: SceneGuide }) {
  return (
    <div
      className={guide.actionOpen ? "genesisCard genesisCard--actionOpen" : "genesisCard"}
      data-guide-action-open={guide.actionOpen ? "true" : "false"}
      role="dialog"
      aria-label={guide.title}
    >
      <header>
        <span className="genesisProgress">{t("genesis.progress", { k: guide.progress.k, n: guide.progress.n })}</span>
        <span className="genesisSim">{t("genesis.sim")}</span>
      </header>
      <h2>{guide.title}</h2>
      <p>{guide.actionOpen && guide.during ? guide.during : guide.body}</p>
      <div className="genesisActions">
        {guide.onBack && (
          <button className="genesisGhost" onClick={guide.onBack} tabIndex={0} type="button">
            {t("genesis.back")}
          </button>
        )}
        {!guide.actionOpen && guide.cta && (
          <button className="genesisCta" onClick={guide.cta.onClick} tabIndex={0} type="button">
            {guide.cta.label}
          </button>
        )}
        {guide.final && (
          <>
            <a className="genesisCta" href={guide.final.exploreHref} tabIndex={0}>
              {t("genesis.explore")}
            </a>
            <button className="genesisGhost" onClick={guide.final.onRestart} tabIndex={0} type="button">
              {t("genesis.restart")}
            </button>
          </>
        )}
      </div>
      <a className="genesisSkip" href={guide.skipHref} tabIndex={0}>
        {t("genesis.skip")}
      </a>
    </div>
  );
}
