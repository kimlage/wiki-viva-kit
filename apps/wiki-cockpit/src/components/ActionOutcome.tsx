import type { PageContent, PageRecord } from "../types";
import { EvidenceMarkdown } from "./EvidenceMarkdown";

const COPY = {
  pt: { history: "Histórico desta ação", connection: "Conexão atual do executor", unknown: "Não verificada nesta interface", automation: "Automação geral", telemetry: "Esta tela não recebe atividade do executor em tempo real. Uma conclusão registrada não confirma uma conexão atual.", results: "Resultado e evidências", recorded: "A conclusão está registrada na wiki. Consulte o resultado e os limites nas evidências.", original: "Registro original da conclusão", cancelled: "Registro original do cancelamento", related: "Artefatos relacionados", read: "Ler", back: "Voltar ao card" },
  en: { history: "Action history", connection: "Current executor connection", unknown: "Not verified in this interface", automation: "General automation", telemetry: "This view does not receive live executor activity. A recorded completion does not confirm a current connection.", results: "Result and evidence", recorded: "Completion is recorded in the wiki. Consult the evidence for the result and its limits.", original: "Original completion record", cancelled: "Original cancellation record", related: "Related artifacts", read: "Read", back: "Back to card" },
  es: { history: "Historial de esta acción", connection: "Conexión actual del ejecutor", unknown: "No verificada en esta interfaz", automation: "Automatización general", telemetry: "Esta vista no recibe actividad del ejecutor en tiempo real. Una finalización registrada no confirma una conexión actual.", results: "Resultado y evidencias", recorded: "La finalización está registrada en la wiki. Consulta el resultado y sus límites en las evidencias.", original: "Registro original de finalización", cancelled: "Registro original de cancelación", related: "Artefactos relacionados", read: "Leer", back: "Volver a la tarjeta" }
};
export function outcomeCopy(language: string) {
  return COPY[language.startsWith("pt") ? "pt" : language.startsWith("es") ? "es" : "en"];
}

// An authored record is historical evidence, never a heartbeat or execution grant.
// No connection claim is inferred from a terminal card or static coordination flags.
export function ActionOutcome({ page, content, pages, language, stateLabel, open }: {
  page: PageRecord; content: PageContent; pages: PageRecord[]; language: string;
  stateLabel: string; open: (id: string) => void;
}) {
  const copy = outcomeCopy(language);
  const state = String(page.work?.state || "unknown");
  const ids = new Set((content.backlinks || []).filter(p => p.page_type === "artifact").map(p => p.page_id));
  // Only already-known canonical pages may be opened by the existing page reader.
  // Paths/URLs in receipts or dialogue are deliberately not file capabilities.
  const artifacts = pages.filter(p => p.page_type === "artifact" && ids.has(p.id));
  const receipt = state === "done" ? page.work?.completion_receipt : state === "cancelled" ? page.work?.cancellation_receipt : null;
  return <section className="boardOutcome" aria-label={copy.results}>
    <dl className="boardExecutionState">
      <div><dt>{copy.history}</dt><dd>{stateLabel}</dd></div>
      <div><dt>{copy.connection}</dt><dd>{copy.unknown}</dd></div>
      <div><dt>{copy.automation}</dt><dd>{copy.unknown}</dd></div>
    </dl>
    <p className="boardProvenance">{copy.telemetry}</p>
    {([['blocker_reason', language.startsWith('pt') ? 'Motivo do bloqueio' : language.startsWith('es') ? 'Motivo del bloqueo' : 'Blocker'], ['next_action', language.startsWith('pt') ? 'Próximo passo' : language.startsWith('es') ? 'Siguiente paso' : 'Next step']] as const).map(([key, label]) => {
      const text = content.frontmatter?.[key];
      return typeof text === 'string' && text ? <div key={key}><h3>{label}</h3><EvidenceMarkdown text={text} links={content.resolved_links} open={open} pages={pages} language={language} /></div> : null;
    })}
    {state === "done" && <p>{copy.recorded}</p>}
    {artifacts.length > 0 && <div className="boardResultLinks"><h3>{copy.related}</h3>{artifacts.map(p => <div key={p.id}>
      <button onClick={() => open(p.id)}>{copy.read}: {p.title}</button>
      <p>{p.summary}</p>
    </div>)}</div>}
    {typeof receipt === "string" && receipt && <details className="boardOriginal"><summary>{state === "done" ? copy.original : copy.cancelled}</summary><p>{receipt}</p></details>}
  </section>;
}
