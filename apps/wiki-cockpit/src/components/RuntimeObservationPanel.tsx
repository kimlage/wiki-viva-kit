import { uiLanguage } from "../data/i18n";
import { latestAttempt } from "../data/runtimeObservations";
import type { RuntimeObservations } from "../data/runtimeObservations";
import "./operational-observation.css";

const COPY = {
  en: { title: "OpenClaw observation", scope: "Retained local evidence. Live activity, queue, account access and scheduler are not observed here.", unknown: "Not observed", noAttempt: "No retained attempt in this scope. This does not prove inactivity.", unavailable: "Observation unavailable. Retained values below may be stale.", observed: "Observed at", executor: "Executor", attempt: "Last attempt", result: "Result captured", status: "Retained status", incorporation: "Wiki incorporation", incorporated: "Content incorporated on main", receipt: "Receipt on main; content incorporation not proved", pending: "Not proved", wake: "Last recorded wake", expected: "Next expected observation", schedule: "Expected time only; scheduler activity unverified", costs: "Tokens / cost", notMeasured: "Not measured", versions: "Content, process and served frontend", content: "Current checkout", process: "Checkout at process start", started: "Process started", bundle: "Served entry hash", bundleSource: "Frontend source commit", revision: "Content snapshot", restart: "Code or configuration changed since process start; restart required", warning: "Process-start SHA is not proof of every loaded module. The served entry hash does not identify a source commit.", result_retained: "Result retained", resolved_without_result: "Resolved without a result", awaiting_reconciliation: "Awaiting reconciliation; live execution unknown", errors: "Some retained evidence is unavailable" },
  pt: { title: "Observação OpenClaw", scope: "Evidência local preservada. Atividade ao vivo, fila, acesso à conta e agendador não são observados aqui.", unknown: "Não observado", noAttempt: "Nenhuma tentativa preservada neste escopo. Isso não comprova inatividade.", unavailable: "Observação indisponível. Os valores preservados abaixo podem estar desatualizados.", observed: "Observado em", executor: "Executor", attempt: "Última tentativa", result: "Resultado capturado", status: "Estado preservado", incorporation: "Incorporação na wiki", incorporated: "Conteúdo incorporado na main", receipt: "Recibo na main; incorporação do conteúdo não comprovada", pending: "Não comprovada", wake: "Último despertar registrado", expected: "Próxima observação esperada", schedule: "Horário previsto; atividade do agendador não verificada", costs: "Tokens / custo", notMeasured: "Não medidos", versions: "Conteúdo, processo e frontend servido", content: "Checkout atual", process: "Checkout no início do processo", started: "Início do processo", bundle: "Hash da entrada servida", bundleSource: "Commit de origem do frontend", revision: "Snapshot de conteúdo", restart: "Código ou configuração mudou desde o início do processo; reinício necessário", warning: "O SHA inicial não comprova cada módulo carregado. O hash da entrada servida não identifica um commit de origem.", result_retained: "Resultado preservado", resolved_without_result: "Resolvida sem resultado", awaiting_reconciliation: "Aguardando reconciliação; execução ao vivo desconhecida", errors: "Parte da evidência preservada está indisponível" },
  es: { title: "Observación OpenClaw", scope: "Evidencia local conservada. No se observan aquí actividad en vivo, cola, acceso a la cuenta ni programador.", unknown: "No observado", noAttempt: "No hay intentos conservados en este ámbito. Esto no prueba inactividad.", unavailable: "Observación no disponible. Los valores conservados pueden estar desactualizados.", observed: "Observado a las", executor: "Ejecutor", attempt: "Último intento", result: "Resultado capturado", status: "Estado conservado", incorporation: "Incorporación en wiki", incorporated: "Contenido incorporado en main", receipt: "Recibo en main; incorporación del contenido no demostrada", pending: "No demostrada", wake: "Última activación registrada", expected: "Próxima observación prevista", schedule: "Hora prevista; actividad del programador no verificada", costs: "Tokens / coste", notMeasured: "No medidos", versions: "Contenido, proceso y frontend servido", content: "Checkout actual", process: "Checkout al iniciar el proceso", started: "Inicio del proceso", bundle: "Hash de entrada servida", bundleSource: "Commit de origen del frontend", revision: "Snapshot de contenido", restart: "El código o la configuración cambió desde el inicio; reinicio necesario", warning: "El SHA inicial no demuestra cada módulo cargado. El hash servido no identifica un commit de origen.", result_retained: "Resultado conservado", resolved_without_result: "Resuelto sin resultado", awaiting_reconciliation: "Pendiente de reconciliación; ejecución en vivo desconocida", errors: "Parte de la evidencia conservada no está disponible" }
};

const META = {
  en: { code: "Current code checkout", content: "Content checkout", transport: "Local TCP transport only", reachable: "Listener reachable", unreachable: "Listener unreachable", not_configured: "Not configured", transportLimit: "Transport reachability does not verify Gateway identity, authorization or execution.", live: "Live execution / pending inputs", native: "Live execution observation is unavailable in read-only mode.", wakeStatus: "Wake result", success: "Success recorded", failure: "Failure recorded", dispatch: "New dispatch in this wake", yes: "Recorded", no: "No new dispatch recorded", profile: "Executor profile", branch: "Proposal branch" },
  pt: { code: "Checkout de código atual", content: "Checkout de conteúdo", transport: "Somente transporte TCP local", reachable: "Porta acessível", unreachable: "Porta inacessível", not_configured: "Não configurado", transportLimit: "Alcançar o transporte não verifica identidade, autorização ou execução do Gateway.", live: "Execução ao vivo / entradas pendentes", native: "Observação da execução ao vivo indisponível em modo somente leitura.", wakeStatus: "Resultado do despertar", success: "Sucesso registrado", failure: "Falha registrada", dispatch: "Novo despacho neste despertar", yes: "Registrado", no: "Nenhum novo despacho registrado", profile: "Perfil do executor", branch: "Branch da proposta" },
  es: { code: "Checkout de código actual", content: "Checkout de contenido", transport: "Solo transporte TCP local", reachable: "Puerto accesible", unreachable: "Puerto inaccesible", not_configured: "No configurado", transportLimit: "Alcanzar el transporte no verifica identidad, autorización ni ejecución del Gateway.", live: "Ejecución en vivo / entradas pendientes", native: "La observación de ejecución en vivo no está disponible en modo de solo lectura.", wakeStatus: "Resultado de activación", success: "Éxito registrado", failure: "Fallo registrado", dispatch: "Nuevo envío en esta activación", yes: "Registrado", no: "Ningún nuevo envío registrado", profile: "Perfil del ejecutor", branch: "Rama de propuesta" }
};

const CHAIN = {
  en: { run: "Run / receipt ID", action: "Canonical action", authorization: "Current authorization", admission: "Retained admission", verified: "Historical guard chain verified", model: "Admitted model / effort", review: "Independent review", failureReviewed: "Resolution without a result reviewed", resultSummary: "Read retained result", partial: "Excerpt only; the hash identifies the full retained text.", resultHash: "Result text SHA-256", resultPath: "Result material", proposalStatus: "Proposal state", reviewHead: "Reviewed commit" },
  pt: { run: "ID da execução / recibo", action: "Ação canônica", authorization: "Autorização vigente", admission: "Admissão preservada", verified: "Cadeia histórica do guard verificada", model: "Modelo / esforço admitidos", review: "Revisão independente", failureReviewed: "Resolução sem resultado revisada", resultSummary: "Ler resultado preservado", partial: "Somente excerto; o hash identifica o texto integral preservado.", resultHash: "SHA-256 do resultado", resultPath: "Material do resultado", proposalStatus: "Estado da proposta", reviewHead: "Commit revisado" },
  es: { run: "ID de ejecución / recibo", action: "Acción canónica", authorization: "Autorización vigente", admission: "Admisión conservada", verified: "Cadena histórica del guard verificada", model: "Modelo / esfuerzo admitidos", review: "Revisión independiente", failureReviewed: "Resolución sin resultado revisada", resultSummary: "Leer resultado conservado", partial: "Solo un extracto; el hash identifica el texto completo conservado.", resultHash: "SHA-256 del resultado", resultPath: "Material del resultado", proposalStatus: "Estado de propuesta", reviewHead: "Commit revisado" }
};

export function RuntimeObservationPanel({ observation, unavailable = false, actionId, snapshotId, versions = false }: {
  observation: RuntimeObservations | null; unavailable?: boolean; actionId?: string; snapshotId?: string; versions?: boolean;
}) {
  const copy = { ...COPY[uiLanguage()], ...META[uiLanguage()], ...CHAIN[uiLanguage()] };
  const codeHashes = uiLanguage() === "pt" ? ["SHA-256 do código no início", "SHA-256 do código atual"]
    : uiLanguage() === "es" ? ["SHA-256 del código inicial", "SHA-256 del código actual"]
    : ["Code SHA-256 at process start", "Current code SHA-256"];
  const attempt = latestAttempt(observation, actionId);
  const rules = observation?.openclaw.rules.filter(rule => !actionId || rule.action_id === actionId) || [];
  const field = (label: string, value?: string | null) => <div key={label}><dt>{label}</dt><dd>{value || copy.unknown}</dd></div>;
  return <section className="runtimeObservation" aria-label={copy.title}>
    <h3>{copy.title}</h3><p>{copy.scope}</p>
    {unavailable && <p role="status">{copy.unavailable}</p>}
    <dl>{field(copy.executor, "OpenClaw")}{field(copy.observed, observation?.observed_at)}{field(copy.live, copy.unknown)}{field(copy.costs, copy.notMeasured)}</dl>
    {observation?.openclaw.transport && <><dl>{field(copy.transport, observation.openclaw.transport.status === "unavailable" ? null : copy[observation.openclaw.transport.status])}{field(copy.observed, observation.openclaw.transport.observed_at)}</dl><p>{copy.transportLimit}</p></>}
    {Boolean(observation?.openclaw.native_observations.length) && <p>{copy.native}</p>}
    {attempt ? <><dl>{field(copy.run, attempt.run_id || attempt.effect_key)}
      <div><dt>{copy.action}</dt><dd><a href={`/board?action=${encodeURIComponent(attempt.action_id)}`}>{attempt.action_id}</a></dd></div>
      {field(copy.attempt, attempt.attempted_at)}{field(copy.status, copy[attempt.status] || copy.unknown)}
      {field(copy.profile, attempt.profile)}
      {field(copy.authorization, copy.unknown)}
      {field(copy.admission, attempt.guard_admission?.status === "retained_chain_verified" ? copy.verified : copy.unknown)}
      {attempt.guard_admission?.status === "retained_chain_verified" && field(copy.model, [attempt.guard_admission.model, attempt.guard_admission.effort].filter(Boolean).join(" / "))}
      {field(copy.result, attempt.result_captured_at)}
      {field(copy.review, attempt.review?.status === "failure_resolution_reviewed" ? copy.failureReviewed : copy.unknown)}
      {attempt.review?.head && field(copy.reviewHead, attempt.review.head)}
      {field(copy.incorporation, attempt.proposal?.content_incorporated_in_main ? copy.incorporated : attempt.proposal?.status === "received_in_main" ? copy.receipt : copy.pending)}
      {attempt.proposal && field(copy.proposalStatus, attempt.proposal.status)}
      {attempt.proposal?.branch && field(copy.branch, attempt.proposal.branch)}
    </dl>{attempt.result && <details><summary>{copy.resultSummary}</summary><pre>{attempt.result.excerpt}</pre>
      {attempt.result.truncated && <p>{copy.partial}</p>}<dl>{field(copy.resultHash, attempt.result.text_sha256)}
      {attempt.proposal?.result_path && field(copy.resultPath, attempt.proposal.result_path)}</dl></details>}
    </> : <p>{observation ? copy.noAttempt : copy.unknown}</p>}
    {rules.map(rule => <div key={rule.rule_id}><strong>{rule.rule_id}</strong><dl>
      {field(copy.wake, rule.last_wake?.observed_at)}{field(copy.wakeStatus, rule.last_wake ? copy[rule.last_wake.status] : null)}
      {field(copy.dispatch, rule.last_wake?.new_dispatch === true ? copy.yes : rule.last_wake?.new_dispatch === false ? copy.no : null)}
      {field(copy.expected, rule.next_expected_observation_at)}</dl><small>{copy.schedule}</small></div>)}
    {Boolean(observation?.openclaw.errors.length) && <p role="status">{copy.errors}</p>}
    {versions && <details><summary>{copy.versions}</summary><dl>
      {field(copy.revision, snapshotId)}{field(copy.content, observation?.operator.content_source_commit)}{field(copy.code, observation?.operator.current_source_commit)}
      {field(copy.process, observation?.operator.boot_source_commit)}{field(copy.started, observation?.operator.started_at)}
      {field(codeHashes[0], observation?.operator.boot_code_sha256)}{field(codeHashes[1], observation?.operator.current_code_sha256)}
      {field(copy.bundle, observation?.operator.frontend.entry_sha256)}{field(copy.bundleSource, null)}
    </dl>{observation?.operator.restart_required && <p role="status">{copy.restart}</p>}<p>{copy.warning}</p></details>}
  </section>;
}
