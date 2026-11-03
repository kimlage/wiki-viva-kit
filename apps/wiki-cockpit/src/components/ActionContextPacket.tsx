import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { getAdminSessionDescription, subscribeAdminSession } from "../application/adminSession";
import type { ContextPacketCapability, ContextPacketPort, ContextPacketResult } from "../data/contextPackets";
import type { PageRecord } from "../types";

const COPY = {
  en: { title: "Context for this work", unavailable: "Protected binding or authorization unavailable. Use local administration to authenticate and check again. Protected context is unavailable for this request.", unknown: "Context capability not observed.", check: "Check context availability", context: "Authorized context", choose: "Select a context", goal: "Reading objective", goalValue: "Interpret the authorized work page to prepare the explicitly selected output", output: "Output destination", integrator: "Requested integrator role", budget: "Packet limit (bytes)", prepare: "Read approved context for this work", working: "Preparing context…", readonly: "Protected context is unavailable in this view.", scope: "This request selects the work page at an approved revision. The server resolves its owner and checks the document hash, policy and approved connections before including its content. Coordinator profiles do not grant access.", approved: "Approved revision", evidence: "Selected work page", mode: "Context mode", modeValue: "Approved policy and content", coverage: "Coverage", coverageValue: "Explicit selection; broader coverage remains incomplete", bytes: "Packet bytes", digest: "Packet digest", inputs: "Selected pages and excerpts", missing: "Declared omissions", assembled: "Context assembled for this work. Reading by an executor, execution and integration require their own evidence.", unknownResult: "Packet result unknown. Check availability and the work revision before a new request.", blocker: "Context impediment", status: "State", action: "Action", target: "Target", reason: "Reason", owner: "Owner", required: "Required action", destination: "Where to act", resume: "Resume condition", notObserved: "Not observed", pending: "Pending", denied: "Denied", uncertain: "Uncertain", boundary: "Context boundary", declaration: "Policy boundary", reasonValue: "Read the selected canonical work page to prepare its expected output.", omission: "Other evidence was not selected by this request." },
  pt: { title: "Contexto deste trabalho", unavailable: "Binding protegido ou autorização indisponível. Autentique-se na administração local e confira novamente. O contexto protegido está indisponível para este pedido.", unknown: "Capacidade de contexto não observada.", check: "Conferir disponibilidade do contexto", context: "Contexto autorizado", choose: "Selecione um contexto", goal: "Objetivo de leitura", goalValue: "Interpretar a página de trabalho autorizada para preparar a saída explicitamente selecionada", output: "Destino da saída", integrator: "Papel de integração solicitado", budget: "Limite do pacote (bytes)", prepare: "Ler contexto aprovado deste trabalho", working: "Preparando contexto…", readonly: "Contexto protegido indisponível nesta visão.", scope: "Este pedido seleciona a página do trabalho em revisão aprovada. O servidor resolve o dono e confere hash, política e conexões aprovadas antes de incluir o conteúdo. Perfis de coordenação não concedem acesso.", approved: "Revisão aprovada", evidence: "Página do trabalho selecionada", mode: "Modo de contexto", modeValue: "Política e conteúdo aprovados", coverage: "Cobertura", coverageValue: "Seleção explícita; cobertura mais ampla permanece incompleta", bytes: "Bytes do pacote", digest: "Digest do pacote", inputs: "Páginas e recortes selecionados", missing: "Omissões declaradas", assembled: "Contexto montado para este trabalho. Leitura pelo executor, execução e integração exigem evidências próprias.", unknownResult: "Resultado do pacote desconhecido. Confira disponibilidade e revisão do trabalho antes de um novo pedido.", blocker: "Impedimento de contexto", status: "Estado", action: "Ação", target: "Alvo", reason: "Motivo", owner: "Responsável", required: "Ação necessária", destination: "Onde agir", resume: "Condição de retomada", notObserved: "Não observado", pending: "Pendente", denied: "Negado", uncertain: "Incerto", boundary: "Fronteira do contexto", declaration: "Limite da política", reasonValue: "Ler a página canônica do trabalho selecionado para preparar o resultado esperado.", omission: "Outras evidências não foram selecionadas por este pedido." },
  es: { title: "Contexto de este trabajo", unavailable: "Binding protegido o autorización no disponible. Autentíquese en la administración local y compruebe de nuevo. El contexto protegido no está disponible para esta solicitud.", unknown: "Capacidad de contexto no observada.", check: "Comprobar disponibilidad de contexto", context: "Contexto autorizado", choose: "Seleccione un contexto", goal: "Objetivo de lectura", goalValue: "Interpretar la página de trabajo autorizada para preparar la salida explícitamente seleccionada", output: "Destino de salida", integrator: "Rol de integración solicitado", budget: "Límite del paquete (bytes)", prepare: "Leer contexto aprobado de este trabajo", working: "Preparando contexto…", readonly: "Contexto protegido no disponible en esta vista.", scope: "Esta solicitud selecciona la página del trabajo en una revisión aprobada. El servidor determina el propietario y comprueba hash, política y conexiones aprobadas antes de incluir su contenido. Los perfiles de coordinación no conceden acceso.", approved: "Revisión aprobada", evidence: "Página de trabajo seleccionada", mode: "Modo de contexto", modeValue: "Política y contenido aprobados", coverage: "Cobertura", coverageValue: "Selección explícita; cobertura más amplia sigue incompleta", bytes: "Bytes del paquete", digest: "Digest del paquete", inputs: "Páginas y recortes seleccionados", missing: "Omisiones declaradas", assembled: "Contexto preparado para este trabajo. La lectura por un ejecutor, ejecución e integración requieren evidencia propia.", unknownResult: "Resultado de paquete desconocido. Compruebe disponibilidad y revisión del trabajo antes de otra solicitud.", blocker: "Impedimento de contexto", status: "Estado", action: "Acción", target: "Destino", reason: "Motivo", owner: "Responsable", required: "Acción necesaria", destination: "Dónde actuar", resume: "Condición para reanudar", notObserved: "No observado", pending: "Pendiente", denied: "Denegado", uncertain: "Incierto", boundary: "Frontera del contexto", declaration: "Límite de política", reasonValue: "Leer la página canónica del trabajo seleccionado para preparar su resultado esperado.", omission: "Esta solicitud no seleccionó otra evidencia." }
};
export function ActionContextPacket({ reader, page, language, disabled = false }: {
  reader: ContextPacketPort; page: PageRecord; language: string; disabled?: boolean;
}) {
  const copy = COPY[language.startsWith("pt") ? "pt" : language.startsWith("es") ? "es" : "en"];
  const session = useSyncExternalStore(subscribeAdminSession, getAdminSessionDescription);
  const [capability, setCapability] = useState<ContextPacketCapability | null>(null);
  const [checking, setChecking] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [context, setContext] = useState("");
  const [taskId] = useState(() => `context-work-${globalThis.crypto.randomUUID()}`);
  const [output, setOutput] = useState("");
  const [budget, setBudget] = useState(65536);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ContextPacketResult | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    activeRequest.current?.abort(); setBusy(false); setCapability(null); setResult(null); setContext("");
    if (disabled) { setChecking(false); return () => abort.abort(); }
    setChecking(true);
    void reader.loadCapability({ signal: abort.signal }).then(value => {
      if (!abort.signal.aborted) { setCapability(value); if (value.available && value.contexts.length === 1) setContext(value.contexts[0]); }
    }).catch(() => { if (!abort.signal.aborted) setCapability(null); })
      .finally(() => { if (!abort.signal.aborted) setChecking(false); });
    return () => { abort.abort(); activeRequest.current?.abort(); };
  }, [reader, session, refresh, disabled]);
  const prepare = async (event: React.FormEvent) => {
    event.preventDefault();
    if (disabled || busy || checking || !capability?.available || !capability.contexts.includes(context) || !output.trim()
      || !/^[a-f0-9]{64}$/.test(page.content_sha256 || "") || !Number.isInteger(budget) || budget < 4096 || budget > 262144) return;
    const abort = new AbortController(); activeRequest.current = abort;
    setBusy(true); setResult(null);
    try {
      const value = await reader.preparePacket({ context_id: context, approved_revision: capability.policy_revision, content_revision: capability.policy_revision,
        task: { task_id: taskId, goal: copy.goalValue, output, integrator: "independent-integrator", max_bytes: budget,
          evidence: [{ ref: page.path, reason: copy.reasonValue, use: "interpretation", classification: "context", expected_document_sha256: page.content_sha256 }], omissions: [copy.omission] } }, { signal: abort.signal });
      if (!abort.signal.aborted) setResult(value);
    } catch { if (!abort.signal.aborted) setResult({ ok: false, error_code: "context_packet_unknown", blocker: null }); }
    finally { if (!abort.signal.aborted) setBusy(false); }
  };
  const change = (update: () => void) => { setResult(null); update(); };
  const packet = result?.ok ? result.packet : null;
  const impediment = result && !result.ok ? result.blocker : null;
  const field = (label: string, value?: string | null) => <div key={label}><dt>{label}</dt><dd>{value || copy.notObserved}</dd></div>;
  return <section className="boardContextPacket" aria-label={copy.title}>
    <h3>{copy.title}</h3><p>{copy.scope}</p>
    <button type="button" disabled={disabled || checking || busy} onClick={() => setRefresh(n => n + 1)}>{copy.check}</button>
    {disabled ? <p role="status">{copy.readonly}</p> : !capability ? <p role="status">{copy.unknown}</p>
      : !capability.available ? <p role="status">{copy.unavailable}</p> : <form onSubmit={event => void prepare(event)}>
        <fieldset disabled={busy || checking}>
          <dl>{field(copy.approved, capability.policy_revision)}{field(copy.evidence, page.path)}</dl>
          <label>{copy.context}<select value={context} required onChange={e => change(() => setContext(e.target.value))}><option value="">{copy.choose}</option>{capability.contexts.map(id => <option key={id} value={id}>{id}</option>)}</select></label>
          <p>{copy.goal}: {copy.goalValue}</p>
          <label>{copy.output}<input value={output} maxLength={2000} required onChange={e => change(() => setOutput(e.target.value))} /></label>
          <p>{copy.integrator}: independent-integrator</p>
          <label>{copy.budget}<input type="number" value={budget} min={4096} max={262144} required onChange={e => change(() => setBudget(Number(e.target.value)))} /></label>
          <button disabled={!context || !output.trim() || !/^[a-f0-9]{64}$/.test(page.content_sha256 || "")} type="submit">{busy ? copy.working : copy.prepare}</button>
        </fieldset>
      </form>}
    {result && !result.ok && !impediment && <p role="status">{copy.unknownResult}</p>}
    {impediment && <section aria-label={copy.blocker}><h4>{copy.blocker}</h4><dl>
      {field(copy.status, copy[impediment.status])}{field(copy.action, impediment.action)}{field(copy.target, impediment.target)}{field(copy.reason, impediment.reason)}
      {field(copy.owner, impediment.owner)}{field(copy.required, impediment.required_action)}{field(copy.destination, impediment.interface)}{field(copy.resume, impediment.resume_condition)}
    </dl></section>}
    {packet && <div><p role="status">{copy.assembled}</p><dl>
      {field(copy.mode, copy.modeValue)}{field(copy.coverage, copy.coverageValue)}{field(copy.context, packet.context_id)}
      {field(copy.bytes, `${packet.bytes_used} / ${packet.max_bytes}`)}{field(copy.boundary, packet.context.boundary)}
    </dl><details><summary>{copy.inputs}</summary>{packet.inputs.map((input, i) => <details key={`${input.ref}:${i}`}><summary>{input.ref}{input.section ? ` · ${input.section}` : ""}{input.field ? ` · ${input.field}` : ""}</summary><code>{input.revision}</code><pre>{input.text}</pre></details>)}
      <h4>{copy.missing}</h4>{packet.coverage.missing.length ? <ul>{packet.coverage.missing.map((missing, i) => <li key={i}>{missing}</li>)}</ul> : <p>{copy.notObserved}</p>}
      <dl>{field(copy.digest, packet.packet_digest)}{field(copy.declaration, packet.enforcement_claim)}</dl>
    </details></div>}
  </section>;
}
