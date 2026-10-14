import { useCallback, useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import type { OperatorPort } from "../application/ports";
import type { PageContent, PageRecord } from "../types";
import type { SnapshotLoadResult } from "../application/ports";
import { ACTION_STATES, ACTION_TRANSITIONS, actionState, boardPages } from "../data/actionBoard";
import type { ActionEdit, ActionState } from "../data/actionBoard";
import "./action-board.css";

const COPY = {
  en: { title: "Work, in context", subtitle: "One action. Its page, sources and next step.", all: "All contexts", search: "Search actions", terminal: "Show completed and cancelled", refresh: "Refresh", states: ["Ready to plan", "In progress", "Waiting for someone", "Blocked", "Done", "Cancelled"], unknown: "State to review", next: "Next step", blocker: "What is blocking this?", owner: "Responsible", priority: "Priority", priorities: ["Low", "Normal", "High", "Urgent"], save: "Save to wiki", close: "Close", page: "Page and evidence", empty: "No actions in this view", failure: "Could not load the wiki. No sample data was substituted.", readOnly: "Read-only view", proposal: "Changes are saved in this workspace and remain subject to wiki review.", activity: "Executor activity: not connected", receipt: "Result evidence", cancel: "Cancellation reason", state: "Action state", missing: "Not recorded", sources: "Sources", saved: "Saved to the canonical page", conflict: "The page changed. Refresh before saving again.", loading: "Loading wiki…", map: "Explore wiki", total: "actions", snapshot: "Wiki read", open: "Open original page", unavailable: "Page unavailable. Refresh the board.", pending: "A save is in progress.", invalid: "This state cannot be edited here." },
  pt: { title: "Trabalho, com contexto", subtitle: "Uma ação. Sua página, fontes e próximo passo.", all: "Todos os contextos", search: "Buscar ações", terminal: "Mostrar concluídas e canceladas", refresh: "Atualizar", states: ["A fazer", "Em andamento", "Aguardando alguém", "Bloqueado", "Concluído", "Cancelado"], unknown: "Estado a revisar", next: "Próximo passo", blocker: "O que está bloqueando?", owner: "Responsável", priority: "Prioridade", priorities: ["Baixa", "Normal", "Alta", "Urgente"], save: "Salvar na wiki", close: "Fechar", page: "Página e evidências", empty: "Nenhuma ação nesta visão", failure: "Não foi possível ler a wiki. Nenhum dado de exemplo foi usado.", readOnly: "Visão somente leitura", proposal: "Alterações são salvas nesta área de trabalho e seguem a revisão da wiki.", activity: "Atividade do executor: não conectada", receipt: "Evidência do resultado", cancel: "Motivo do cancelamento", state: "Estado da ação", missing: "Não registrado", sources: "Fontes", saved: "Salvo na página canônica", conflict: "A página mudou. Atualize antes de salvar novamente.", loading: "Lendo a wiki…", map: "Explorar wiki", total: "ações", snapshot: "Leitura da wiki", open: "Abrir página original", unavailable: "Página indisponível. Atualize o quadro.", pending: "Há uma gravação em andamento.", invalid: "Este estado não pode ser editado aqui." },
  es: { title: "Trabajo, con contexto", subtitle: "Una acción. Su página, fuentes y próximo paso.", all: "Todos los contextos", search: "Buscar acciones", terminal: "Mostrar finalizadas y canceladas", refresh: "Actualizar", states: ["Por hacer", "En curso", "Esperando a alguien", "Bloqueado", "Completado", "Cancelado"], unknown: "Estado por revisar", next: "Próximo paso", blocker: "¿Qué lo bloquea?", owner: "Responsable", priority: "Prioridad", priorities: ["Baja", "Normal", "Alta", "Urgente"], save: "Guardar en wiki", close: "Cerrar", page: "Página y evidencias", empty: "No hay acciones en esta vista", failure: "No se pudo leer la wiki. No se usaron datos de ejemplo.", readOnly: "Solo lectura", proposal: "Los cambios se guardan en este espacio y requieren revisión de la wiki.", activity: "Actividad del ejecutor: no conectada", receipt: "Evidencia del resultado", cancel: "Motivo de cancelación", state: "Estado de la acción", missing: "No registrado", sources: "Fuentes", saved: "Guardado en la página canónica", conflict: "La página cambió. Actualiza antes de guardar.", loading: "Leyendo wiki…", map: "Explorar wiki", total: "acciones", snapshot: "Lectura de wiki", open: "Abrir página original", unavailable: "Página no disponible. Actualiza el tablero.", pending: "Hay una escritura en curso.", invalid: "Este estado no se puede editar aquí." }
};
export type BoardOperator = Pick<OperatorPort, "loadSnapshotBundle" | "loadPageContent">;
export function ActionBoard({ operator, save, demo = false }: { operator: BoardOperator; save: (edit: ActionEdit) => Promise<void>; demo?: boolean }) {
  const [loaded, setLoaded] = useState<SnapshotLoadResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [context, setContext] = useState("");
  const [query, setQuery] = useState("");
  const [terminal, setTerminal] = useState(false);
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState<PageContent | null>(null);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const requestId = useRef(0);
  const language = loaded?.bundle.manifest.repo.language || loaded?.runtime.language || "en";
  const copy = COPY[language.startsWith("pt") ? "pt" : language.startsWith("es") ? "es" : "en"];
  const reload = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true); setError(""); setContent(null);
    try {
      const next = await operator.loadSnapshotBundle({ demo });
      if (!demo && (next.runtime.mode === "sample_fallback" || next.source.includes("/sample-snapshot"))) throw Error("sample fallback refused");
      if (id === requestId.current) setLoaded(next);
    } catch { if (id === requestId.current) { setLoaded(null); setError("load"); } }
    finally { if (id === requestId.current) setLoading(false); }
  }, [operator, demo]);
  useEffect(() => { void reload(); return () => { requestId.current++; }; }, [reload]);
  const pages = loaded?.bundle.pages.pages || [];
  const page = pages.find(p => p.id === selected);
  const writable = !demo && !loading && !error && loaded?.runtime.mode === "local_operator";
  useEffect(() => {
    setContent(null);
    if (!page || !loaded) return;
    const abort = new AbortController();
    void operator.loadPageContent(page.id, { demo, snapshotSource: loaded.source, snapshotId: loaded.bundle.manifest.snapshot_id, integrity: loaded.bundle.manifest.integrity, signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setContent(value); })
      .catch(() => { if (!abort.signal.aborted) setContent({ ok: false }); });
    return () => abort.abort();
  }, [page, loaded, operator, demo]);
  const rows = boardPages(pages, context, query, terminal);
  const columns = [...ACTION_STATES.filter(s => terminal || !["done", "cancelled"].includes(s)), "unknown"] as const;
  const titleFor = (state: string) => state === "unknown" ? copy.unknown : copy.states[ACTION_STATES.indexOf(state as ActionState)];
  const select = (id: string) => { if (!savingRef.current) { setSelected(id); setNotice(""); } };
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (savingRef.current || !writable || !page || !content?.ok || !page.content_sha256) return;
    const values = new FormData(event.currentTarget);
    const state = String(values.get("state")) as ActionState;
    const edit: ActionEdit = { page_ref: page.path, expected_sha256: page.content_sha256, next_state: state, priority: String(values.get("priority")) };
    if (!["done", "cancelled"].includes(state)) edit.next_action = String(values.get("next_action") || "");
    if (state === "blocked") edit.blocker_reason = String(values.get("blocker_reason") || "");
    if (state === "done") edit.completion_receipt = String(values.get("completion_receipt") || "");
    if (state === "cancelled") edit.cancellation_receipt = String(values.get("cancellation_receipt") || "");
    savingRef.current = true; setSaving(true); setNotice("");
    try { await save(edit); setNotice(copy.saved); await reload(); }
    catch (err) { setNotice(err instanceof Error && /stale_action_revision/.test(err.message) ? copy.conflict : String(err)); }
    finally { savingRef.current = false; setSaving(false); }
  }
  return <main className="actionBoard">
    <header className="boardHeader"><div><span className="boardEyebrow">WIKI VIVA · KANBAN {demo ? "· DEMO" : ""}</span><h1>{copy.title}</h1><p>{copy.subtitle}</p></div><div className="boardHeaderActions"><a href={demo ? "/demo/w" : "/w"}>{copy.map}</a><button disabled={loading || saving} onClick={() => void reload()}>{copy.refresh}</button></div></header>
    <section className="boardToolbar" aria-label="Filters"><label><span>{copy.all}</span><select value={context} onChange={e => setContext(e.target.value)}><option value="">{copy.all}</option>{[...new Set(pages.filter(p => p.page_type === "action").map(p => p.context))].sort().map(c => <option key={c}>{c}</option>)}</select></label><label className="boardSearch"><span>{copy.search}</span><input value={query} onChange={e => setQuery(e.target.value)} type="search" /></label><label className="boardToggle"><input type="checkbox" checked={terminal} onChange={e => setTerminal(e.target.checked)} />{copy.terminal}</label><strong>{rows.length} {copy.total}</strong></section>
    <p className="boardProvenance">{loading ? copy.loading : error ? copy.failure : `${copy.snapshot}: ${loaded?.bundle.manifest.generated_at || "—"} · ${loaded?.bundle.git.current_branch || ""}`} {!writable && !loading && !error ? `· ${copy.readOnly}` : ""}</p>
    {error && <p role="alert">{copy.failure}</p>}
    {!loading && !error && <div className={page ? "boardLayout hasSelection" : "boardLayout"}><section className="boardColumns" aria-label="Kanban">{columns.filter(s => s !== "unknown" || rows.some(p => actionState(p) === "unknown")).map(state => <section className={`boardColumn board-${state}`} key={state} aria-label={titleFor(state)}><h2>{titleFor(state)} <span>{rows.filter(p => actionState(p) === state).length}</span></h2>{rows.filter(p => actionState(p) === state).map(p => <button className={`boardCard ${p.id === selected ? "selected" : ""}`} key={p.id} onClick={() => select(p.id)}><span className="boardCardContext">{p.context} <b data-priority={String(p.work?.priority)}>{copy.priorities[["low", "normal", "high", "urgent"].indexOf(String(p.work?.priority))] || String(p.work?.priority || "")}</b></span><h3>{p.title}</h3><p>{String(p.work?.next_action || p.work?.blocker_reason || p.summary || copy.missing)}</p><small>{copy.owner}: {String(p.work?.owner_ref || copy.missing)}</small></button>)}</section>)}</section>
      {page && <aside className="boardDetail" aria-label={copy.page}><div className="boardDetailTop"><span>{page.context}</span><button disabled={saving} onClick={() => select("")}>{copy.close}</button></div><h2>{page.title}</h2><p className="boardActivity">{copy.activity}</p>{notice && <p role="status" className="boardNotice">{notice}</p>}
      {content === null ? <p>{copy.loading}</p> : !content.ok ? <p role="alert">{copy.unavailable}</p> : <>
        <ActionForm key={`${page.id}:${page.content_sha256}`} page={page} writable={Boolean(writable && page.content_sha256)} saving={saving} copy={copy} submit={submit} />
        <section className="boardEvidence"><h3>{copy.sources}</h3>{content.source_refs?.map(s => <p key={s.ref}>{s.resolved ? <button onClick={() => select(s.page_id)}>{s.title}</button> : s.ref}</p>)}<h3>{copy.page}</h3><article className="boardMarkdown" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(content.body || "", { async: false }), { FORBID_TAGS: ["img", "iframe", "form"], FORBID_ATTR: ["style"] }) }} onClick={event => {
          const anchor = (event.target as HTMLElement).closest("a"); if (!anchor) return;
          const link = content.resolved_links?.find(l => l.href === anchor.getAttribute("href"));
          if (link?.kind === "page") { event.preventDefault(); select(link.page_id); }
          else if (anchor.getAttribute("href")?.startsWith("#")) { event.preventDefault(); }
          else { event.preventDefault(); if (link?.kind === "external" && /^https?:\/\//.test(link.href)) window.open(link.href, "_blank", "noopener,noreferrer"); }
        }} /></section></>}
      </aside>}
    </div>}
    {!loading && !error && rows.length === 0 && <p className="boardEmpty">{copy.empty}</p>}
  </main>;
}
function ActionForm({ page, writable, saving, copy, submit }: { page: PageRecord; writable: boolean; saving: boolean; copy: typeof COPY.en; submit: (event: React.FormEvent<HTMLFormElement>) => void }) {
  const current = actionState(page); const [state, setState] = useState(current);
  if (page.page_type !== "action") return null;
  if (current === "unknown") return <p>{copy.invalid}</p>;
  const terminal = ["done", "cancelled"].includes(current);
  return <form onSubmit={submit} className="boardForm"><fieldset disabled={!writable || saving || terminal}>
    <label>{copy.state}<select name="state" value={state} onChange={e => setState(e.target.value as ActionState)}>{[current, ...ACTION_TRANSITIONS[current]].map(s => <option key={s} value={s}>{copy.states[ACTION_STATES.indexOf(s)]}</option>)}</select></label>
    <label>{copy.priority}<select name="priority" defaultValue={String(page.work?.priority || "normal")}>{!["low", "normal", "high", "urgent"].includes(String(page.work?.priority || "normal")) && <option value={String(page.work?.priority)} disabled>{String(page.work?.priority)}</option>}{["low", "normal", "high", "urgent"].map((p,i) => <option key={p} value={p}>{copy.priorities[i]}</option>)}</select></label>
    {!["done", "cancelled"].includes(state) && <label>{copy.next}<textarea name="next_action" defaultValue={String(page.work?.next_action || "")} maxLength={2000} required /></label>}
    {state === "blocked" && <label>{copy.blocker}<textarea name="blocker_reason" defaultValue={String(page.work?.blocker_reason || "")} required maxLength={2000} /></label>}
    {state === "done" && <label>{copy.receipt}<textarea name="completion_receipt" defaultValue={String(page.work?.completion_receipt || "")} required maxLength={2000} /></label>}
    {state === "cancelled" && <label>{copy.cancel}<textarea name="cancellation_receipt" defaultValue={String(page.work?.cancellation_receipt || "")} required maxLength={2000} /></label>}
    {!terminal && writable && <button className="boardSave" type="submit">{saving ? copy.pending : copy.save}</button>}
    </fieldset><p className="boardProvenance">{writable ? copy.proposal : copy.readOnly}</p></form>;
}
