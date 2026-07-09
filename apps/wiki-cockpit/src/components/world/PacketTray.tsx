// Decision-packet slide-up tray (replaces ImpactBundlePanel): the collected
// pages with open/remove per row, plus the packet-level ops actions
// (inspect changes, honesty gates, approval summary).

import { GitPullRequest, Play } from "lucide-react";
import { t } from "../../data/i18n";
import { contextLabel, isRawData } from "../../data/presentation";
import type { OperatorCommandCard, PageRecord } from "../../types";
import { HelpTip } from "../HelpTip";

const ACTION_TITLES: Record<string, string> = {
  "git-status": "Check work state",
  "review-local-changes": "Inspect changed content",
  "run-honesty-gates": "Verify approval readiness",
  "pr-summary": "Prepare approval summary",
  "graph-check": "Check related content"
};

function operatorCommandTitle(action: OperatorCommandCard): string {
  return ACTION_TITLES[action.id] || action.title;
}

export function PacketTray({
  packetPages,
  reviewCommand,
  gateCommand,
  prCommand,
  onRun,
  onOpenPage,
  onTogglePacket,
  onClearPacket,
  onClose
}: {
  packetPages: PageRecord[];
  reviewCommand?: OperatorCommandCard;
  gateCommand?: OperatorCommandCard;
  prCommand?: OperatorCommandCard;
  onRun: (action: OperatorCommandCard) => void;
  onOpenPage: (id: string) => void;
  onTogglePacket: (id: string) => void;
  onClearPacket: () => void;
  onClose: () => void;
}) {
  return (
    <div className="packetTray" role="region" aria-label={t("world.packet", { n: packetPages.length })}>
      <header>
        <strong>{t("world.packet", { n: packetPages.length })}</strong>
        <HelpTip term="packet" />
        <button className="textButton" onClick={onClearPacket} disabled={packetPages.length === 0} type="button">
          {t("misc.clear")}
        </button>
        <button className="readerClose" onClick={onClose} title="Fechar" type="button">
          ×
        </button>
      </header>
      <div className="packetRows">
        {packetPages.map((page) => (
          <div className="packetRow" key={page.id}>
            <button className="textButton" onClick={() => onOpenPage(page.id)} title={page.path} type="button">
              {page.title}
            </button>
            <small>
              {contextLabel(page.context || "system")}
              {isRawData(page.page_type) ? ` · ${t("world.raw")}` : ""}
              {page.summary_truncated ? ` · ${t("world.partialSummary")}` : ""}
            </small>
            <button className="textButton" onClick={() => onTogglePacket(page.id)} type="button">
              {t("misc.remove")}
            </button>
          </div>
        ))}
        {packetPages.length === 0 && <p>{t("misc.packetEmpty")}</p>}
      </div>
      <div className="packetActions">
        {reviewCommand && (
          <button className="secondaryButton" onClick={() => onRun(reviewCommand)} type="button">
            <Play size={14} />
            <span>{operatorCommandTitle(reviewCommand)}</span>
          </button>
        )}
        {gateCommand && (
          <button className="secondaryButton" onClick={() => onRun(gateCommand)} type="button">
            <Play size={14} />
            <span>{operatorCommandTitle(gateCommand)}</span>
          </button>
        )}
        {prCommand && (
          <button className="secondaryButton" onClick={() => onRun(prCommand)} type="button">
            <GitPullRequest size={14} />
            <span>{operatorCommandTitle(prCommand)}</span>
          </button>
        )}
      </div>
    </div>
  );
}
