import { uiLanguage } from "../data/i18n";
import type { RuntimeObservations } from "../data/runtimeObservations";
import "./operational-observation.css";

const COPY = {
  en: { title: "Operator observation", scope: "Observed versions of this operator only. Executor activity, account access and scheduler installation are not observed here.", unknown: "Not observed", unavailable: "Observation unavailable. Retained values below may be stale.", observed: "Observed at", versions: "Content, process and served frontend", content: "Content checkout", code: "Current code checkout", process: "Checkout at process start", started: "Process started", bootHash: "Code SHA-256 at process start", codeHash: "Current code SHA-256", bundle: "Served entry hash", bundleSource: "Frontend source commit", revision: "Content snapshot", restart: "Code or configuration changed since process start; restart required", refresh: "Refresh reads content and observations. Process code or configuration requires a controlled restart; frontend changes require a new bundle. Refresh does not perform either operation.", warning: "Process-start SHA is not proof of every loaded module. The served entry hash does not identify a source commit." },
  pt: { title: "Observação do operador", scope: "Somente versões observadas deste operador. Atividade de executores, acesso à conta e instalação de agenda não são observados aqui.", unknown: "Não observado", unavailable: "Observação indisponível. Os valores preservados abaixo podem estar desatualizados.", observed: "Observado em", versions: "Conteúdo, processo e frontend servido", content: "Checkout de conteúdo", code: "Checkout de código atual", process: "Checkout no início do processo", started: "Início do processo", bootHash: "SHA-256 do código no início", codeHash: "SHA-256 do código atual", bundle: "Hash da entrada servida", bundleSource: "Commit de origem do frontend", revision: "Snapshot de conteúdo", restart: "Código ou configuração mudou desde o início do processo; reinício necessário", refresh: "Atualizar relê conteúdo e observações. Código ou configuração de processo exige reinício controlado; mudanças no frontend exigem novo bundle. Atualizar não realiza essas operações.", warning: "O SHA inicial não comprova cada módulo carregado. O hash da entrada servida não identifica um commit de origem." },
  es: { title: "Observación del operador", scope: "Solo versiones observadas de este operador. Aquí no se observa actividad de ejecutores, acceso a la cuenta ni instalación de agenda.", unknown: "No observado", unavailable: "Observación no disponible. Los valores conservados pueden estar desactualizados.", observed: "Observado a las", versions: "Contenido, proceso y frontend servido", content: "Checkout de contenido", code: "Checkout de código actual", process: "Checkout al iniciar el proceso", started: "Inicio del proceso", bootHash: "SHA-256 del código inicial", codeHash: "SHA-256 del código actual", bundle: "Hash de entrada servida", bundleSource: "Commit de origen del frontend", revision: "Snapshot de contenido", restart: "El código o la configuración cambió desde el inicio; reinicio necesario", refresh: "Actualizar vuelve a leer contenido y observaciones. Código o configuración de proceso requiere reinicio controlado; cambios de frontend requieren un nuevo bundle. Actualizar no realiza esas operaciones.", warning: "El SHA inicial no demuestra cada módulo cargado. El hash servido no identifica un commit de origen." }
};

export function RuntimeObservationPanel({ observation, unavailable = false, snapshotId, versions = false }: {
  observation: RuntimeObservations | null; unavailable?: boolean; snapshotId?: string; versions?: boolean;
}) {
  const copy = COPY[uiLanguage()];
  const field = (label: string, value?: string | null) => <div key={label}><dt>{label}</dt><dd>{value || copy.unknown}</dd></div>;
  return <section className="runtimeObservation" aria-label={copy.title}>
    <h3>{copy.title}</h3><p>{copy.scope}</p>
    {unavailable && <p role="status">{copy.unavailable}</p>}
    <dl>{field(copy.observed, observation?.observed_at)}</dl>
    {versions && <details><summary>{copy.versions}</summary><dl>
      {field(copy.revision, snapshotId)}{field(copy.content, observation?.operator.content_source_commit)}
      {field(copy.code, observation?.operator.current_source_commit)}{field(copy.process, observation?.operator.boot_source_commit)}
      {field(copy.started, observation?.operator.started_at)}{field(copy.bootHash, observation?.operator.boot_code_sha256)}
      {field(copy.codeHash, observation?.operator.current_code_sha256)}{field(copy.bundle, observation?.operator.frontend.entry_sha256)}
      {field(copy.bundleSource, observation?.operator.frontend.source_commit)}
    </dl>{observation?.operator.restart_required === true && <p role="status">{copy.restart}</p>}<p>{copy.refresh}</p><p>{copy.warning}</p></details>}
  </section>;
}
