import { uiLanguage } from "../data/i18n";
import "./operational-observation.css";

export function OperationalLinks({ demo = false }: { demo?: boolean }) {
  const language = uiLanguage();
  const label = language === "pt" ? "Frentes" : language === "es" ? "Frentes" : "Work fronts";
  const prefix = demo ? "/demo" : "";
  return <nav className="operationalLinks" aria-label={language === "pt" ? "Trabalho da wiki" : language === "es" ? "Trabajo de la wiki" : "Wiki work"}>
    <a href={`${prefix}/board`}>Kanban</a>
    <a href={`${prefix}/board?view=fronts`}>{label}</a>
  </nav>;
}
