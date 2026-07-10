// DemoGate (/demo): the demo's TITLE SCREEN. Three explicit entry paths serve
// first-time learning, free exploration and the from-zero genesis narrative.
// Nothing here is written, ever; every path uses pre-built fictional data.

import { BookOpen, Compass, Sprout } from "lucide-react";
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
          <a className="demoGateDoor guided" href="/demo/world?tour=1">
            <BookOpen size={22} aria-hidden />
            <strong>{t("demoGate.guided")}</strong>
            <span>{t("demoGate.guidedHint")}</span>
          </a>
          <a className="demoGateDoor world" href="/demo/world?tour=0">
            <Compass size={22} aria-hidden />
            <strong>{t("demoGate.world")}</strong>
            <span>{t("demoGate.worldHint")}</span>
          </a>
          <a className="demoGateDoor genesis" href="/demo/genesis">
            <Sprout size={22} aria-hidden />
            <strong>{t("demoGate.genesis")}</strong>
            <span>{t("demoGate.genesisHint")}</span>
          </a>
        </div>
        <a className="demoGateExit" href="/">
          {t("nav.exitDemo")}
        </a>
      </div>
    </div>
  );
}
