import { uiLanguage } from "../data/i18n";
import type { PageRecord, SourceEntity } from "../types";
import "./operational-observation.css";

const COPY = {
  en: { title: "Source evidence", pending: "Recorded pending work", none: "No recorded trigger pending", capture: "Last recorded ingestion", verification: "Recorded verification", incorporation: "Wiki adoption", gate: "Incorporation gate", access: "Current access / effective identity", unknown: "Unknown", boundary: "A capture, a recorded verification and wiki incorporation are separate. No pending trigger does not certify current source content or account access." },
  pt: { title: "Evidências da fonte", pending: "Pendência registrada", none: "Nenhum gatilho registrado pendente", capture: "Última ingestão registrada", verification: "Verificação registrada", incorporation: "Adoção na wiki", gate: "Gate de incorporação", access: "Acesso atual / identidade efetiva", unknown: "Desconhecidos", boundary: "Captura, verificação registrada e incorporação na wiki são etapas distintas. Ausência de gatilho pendente não comprova conteúdo atual da fonte nem acesso à conta." },
  es: { title: "Evidencia de la fuente", pending: "Trabajo pendiente registrado", none: "Ningún disparador registrado pendiente", capture: "Última ingesta registrada", verification: "Verificación registrada", incorporation: "Adopción en wiki", gate: "Control de incorporación", access: "Acceso actual / identidad efectiva", unknown: "Desconocidos", boundary: "Captura, verificación registrada e incorporación son etapas distintas. La ausencia de disparadores pendientes no certifica contenido actual ni acceso a la cuenta." }
};

export function SourceObservationSummary({ source, pages = [], open }: { source: SourceEntity; pages?: PageRecord[]; open?: (id: string) => void }) {
  const copy = COPY[uiLanguage()];
  const fields = [
    [copy.pending, source.pending_streams > 0 ? String(source.pending_streams) : copy.none],
    [copy.capture, source.lifecycle?.last_ingested_at],
    [copy.verification, source.verification?.recorded_at],
    [copy.incorporation, source.lifecycle?.adoption_state],
    [copy.gate, source.sync.event_closure?.gate_state || source.lifecycle?.pipeline_stage],
    [copy.access, copy.unknown]
  ];
  return <section className="sourceObservation" aria-label={copy.title}><h3>{copy.title}</h3>
    <dl>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || copy.unknown}</dd></div>)}</dl>
    {Boolean(source.verification?.evidence_refs.length) && <ul>{source.verification!.evidence_refs.map(ref => {
      const page = pages.find(value => value.id === ref || value.path === ref);
      return <li key={ref}>{page && open ? <button type="button" onClick={() => open(page.id)}>{page.title}</button> : ref}</li>;
    })}</ul>}
    <p>{copy.boundary}</p>
  </section>;
}
