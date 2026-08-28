// DemoGate (/demo): the demo's TITLE SCREEN. Core learning paths and installed
// pack showcases are explicit, pre-built synthetic universes.
// Nothing here is written, ever; every path uses pre-built fictional data.

import {
  Accessibility,
  Activity,
  BookOpen,
  ChevronDown,
  Compass,
  FlaskConical,
  Gauge,
  GraduationCap,
  Landmark,
  RefreshCw,
  ShieldAlert,
  Sprout,
  Waypoints,
  Workflow
} from "lucide-react";
import { t } from "../data/i18n";

const VALIDATION_LABS = [
  {
    id: "walking_skeleton",
    href: "/demo/w?demo_scenario=walking_skeleton&center=root-alex-rivera&view=quadrants&overlay=actions&tour=0",
    icon: Workflow,
    pages: 8
  },
  {
    id: "normal_operations",
    href: "/demo/w?demo_scenario=normal_operations&center=root-alex-rivera&view=quadrants&overlay=actions&tour=0",
    icon: Activity,
    pages: 107
  },
  {
    id: "dense_stress",
    href: "/demo/w?demo_scenario=dense_stress&center=root-alex-rivera&view=quadrants&overlay=quality&group=family:artifact&tour=0",
    icon: Gauge,
    pages: 378
  },
  {
    id: "source_lifecycle",
    href: "/demo/w?demo_scenario=source_lifecycle&center=root-alex-rivera&view=sources&overlay=freshness&dock=source&tour=0",
    icon: RefreshCw,
    pages: 36
  },
  {
    id: "failures",
    href: "/demo/w?demo_scenario=failures&center=root-alex-rivera&view=radar&overlay=attention&tour=0",
    icon: ShieldAlert,
    pages: 4
  },
  {
    id: "compatibility",
    href: "/demo/w?demo_scenario=compatibility&center=root-alex-rivera&view=quadrants&overlay=actions&tour=0",
    icon: Waypoints,
    pages: 4
  },
  {
    id: "accessibility",
    href: "/demo/w?demo_scenario=accessibility&center=root-alex-rivera&view=quadrants&overlay=actions&tour=0",
    icon: Accessibility,
    pages: 6
  }
] as const;

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
          <a
            className="demoGateDoor pack study"
            href="/demo/w?demo_scenario=study_research_showcase&center=root-study-research-showcase&view=quadrants&overlay=evidence&tour=0"
          >
            <GraduationCap size={22} aria-hidden />
            <strong>{t("demoGate.study")}</strong>
            <span>{t("demoGate.studyHint")}</span>
          </a>
          <a
            className="demoGateDoor pack finance"
            href="/demo/w?demo_scenario=personal_finance_showcase&center=finance-transaction-income&view=timeline&time_mode=event&tour=0"
          >
            <Landmark size={22} aria-hidden />
            <strong>{t("demoGate.finance")}</strong>
            <span>{t("demoGate.financeHint")}</span>
          </a>
        </div>
        <details className="demoValidationLabs">
          <summary>
            <FlaskConical size={19} aria-hidden />
            <span>
              <strong>{t("demoGate.validation.title")}</strong>
              <small>{t("demoGate.validation.hint")}</small>
            </span>
            <ChevronDown className="demoValidationChevron" size={17} aria-hidden />
          </summary>
          <nav className="demoValidationGrid" aria-label={t("demoGate.validation.aria")}>
            {VALIDATION_LABS.map((lab) => {
              const Icon = lab.icon;
              return (
                <a
                  className="demoValidationLab"
                  data-demo-scenario={lab.id}
                  href={lab.href}
                  key={lab.id}
                >
                  <Icon size={17} aria-hidden />
                  <span className="demoValidationCopy">
                    <strong>{t(`demoGate.validation.${lab.id}`)}</strong>
                    <small>{t(`demoGate.validation.${lab.id}.hint`)}</small>
                  </span>
                  <span className="demoValidationCount">
                    {t("demoGate.validation.pages", { n: lab.pages })}
                  </span>
                </a>
              );
            })}
          </nav>
        </details>
        <a className="demoGateExit" href="/">
          {t("nav.exitDemo")}
        </a>
      </div>
    </div>
  );
}
