import type { WorkFront } from "../data/actionBoard";
import type { PageRecord } from "../types";
import { uiLanguage } from "../data/i18n";

const COPY = {
  en: { title: "Work fronts", intro: "A view of existing pages and linked actions. Recorded states do not prove live execution.", unavailable: "Front projection unavailable for this content revision.", empty: "No front is declared in this projection.", owner: "Owner", state: "Recorded state", recorded: "Last page record", next: "Next step", blocker: "Dependency / pause", missing: "Not recorded", evidence: "Evidence", actions: "Existing actions", read: "Read front page", access: "Live execution and effective access: unknown", warnings: "Some front references could not be resolved." },
  pt: { title: "Frentes", intro: "Visão das páginas existentes e suas ações vinculadas. Estados registrados não comprovam execução ao vivo.", unavailable: "Projeção de frentes indisponível para esta revisão do conteúdo.", empty: "Nenhuma frente declarada nesta projeção.", owner: "Responsável", state: "Estado registrado", recorded: "Último registro da página", next: "Próximo passo", blocker: "Dependência / pausa", missing: "Não registrado", evidence: "Evidências", actions: "Ações existentes", read: "Ler página da frente", access: "Execução ao vivo e acesso efetivo: desconhecidos", warnings: "Algumas referências de frentes não puderam ser resolvidas." },
  es: { title: "Frentes", intro: "Vista de páginas existentes y acciones vinculadas. Los estados registrados no prueban ejecución en vivo.", unavailable: "Proyección de frentes no disponible para esta revisión.", empty: "No hay frentes declarados en esta proyección.", owner: "Responsable", state: "Estado registrado", recorded: "Último registro de página", next: "Próximo paso", blocker: "Dependencia / pausa", missing: "No registrado", evidence: "Evidencia", actions: "Acciones existentes", read: "Leer página del frente", access: "Ejecución en vivo y acceso efectivo: desconocidos", warnings: "No se pudieron resolver algunas referencias." }
};

export function WorkFronts({ fronts, pages, open, profiles = [], warnings = false }: {
  fronts?: WorkFront[]; pages: PageRecord[]; open: (id: string, opener?: HTMLElement) => void; warnings?: boolean;
  profiles?: { id: string; label: string; scope: string }[];
}) {
  const copy = COPY[uiLanguage()];
  const reference = (ref: string) => {
    const page = pages.find(item => item.id === ref || item.path === ref);
    return page ? <button type="button" onClick={event => open(page.id, event.currentTarget)}>{page.title}</button> : <span>{ref}</span>;
  };
  const boundary = uiLanguage() === "pt" ? "Atribuição e contexto não autorizam retomada. Confira pausas e escopo na página."
    : uiLanguage() === "es" ? "La asignación y el contexto no autorizan reanudar. Consulta pausas y alcance en la página."
    : "Assignment and context do not authorize resumption. Check pauses and scope on the page.";
  return <section className="workFronts" aria-label={copy.title}><h2>{copy.title}</h2><p>{copy.intro}</p><p>{boundary}</p>
    {!fronts ? <p role="status">{copy.unavailable}</p> : fronts.length === 0 ? <p>{copy.empty}</p> : fronts.map(front => <article key={front.page_id}>
      <h3>{front.title}</h3><p>{front.summary}</p><dl>
        <div><dt>{copy.state}</dt><dd>{front.declared_status || copy.missing}</dd></div>
        <div><dt>{copy.owner}</dt><dd>{front.owner_ref ? reference(front.owner_ref) : copy.missing}</dd></div>
        <div><dt>{copy.recorded}</dt><dd>{front.recorded_at || copy.missing}</dd></div>
        <div><dt>{copy.next}</dt><dd>{front.next_action || copy.missing}</dd></div>
        <div><dt>{copy.blocker}</dt><dd>{front.blocker_reason || copy.missing}</dd></div>
      </dl><p>{copy.access}</p><button type="button" onClick={event => open(front.page_id, event.currentTarget)}>{copy.read}</button>
      {front.coordinators.map(id => profiles.find(profile => profile.id === id)).filter(profile => profile !== undefined).map(profile => <details key={profile.id}><summary>{profile.label}</summary><p>{profile.scope}</p></details>)}
      <h4>{copy.actions}</h4><ul>{front.action_ids.map(id => <li key={id}>{reference(id)}</li>)}</ul>
      <h4>{copy.evidence}</h4><ul>{[...new Set([...front.evidence_refs, ...front.source_refs])].map(ref => <li key={ref}>{reference(ref)}</li>)}</ul>
    </article>)}{warnings && <p role="status">{copy.warnings}</p>}
  </section>;
}
