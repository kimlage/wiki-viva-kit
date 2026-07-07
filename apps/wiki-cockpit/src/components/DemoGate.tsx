// DemoGate (/demo): the demo's TITLE SCREEN. Two doors into the same engine —
// found a world from zero and watch the interface materialize template by
// template (the genesis tutorial), or step straight into the finished world.
// Nothing here is written, ever; both doors are pre-built, fictional data.

import { Sparkles, Sprout } from "lucide-react";
import { t } from "../data/i18n";

export function DemoGate() {
  return (
    <div className="demoGate" role="main" aria-label={t("demoGate.title")}>
      <div className="demoGateInner">
        <h1>
          <span className="demoGateBrand">Wiki Viva</span> {t("demoGate.title")}
        </h1>
        <p className="demoGateSubtitle">{t("demoGate.subtitle")}</p>
        <div className="demoGateDoors">
          <a className="demoGateDoor genesis" href="/demo/genesis">
            <Sprout size={22} aria-hidden />
            <strong>{t("demoGate.genesis")}</strong>
            <span>{t("demoGate.genesisHint")}</span>
          </a>
          <a className="demoGateDoor world" href="/demo/world">
            <Sparkles size={22} aria-hidden />
            <strong>{t("demoGate.world")}</strong>
            <span>{t("demoGate.worldHint")}</span>
          </a>
        </div>
        <a className="demoGateExit" href="/">
          {t("nav.exitDemo")}
        </a>
      </div>
    </div>
  );
}
