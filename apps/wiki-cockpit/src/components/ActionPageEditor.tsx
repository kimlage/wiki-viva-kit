import { useState } from "react";
import type { ActionCreate, ActionCreationOptions } from "../data/actionBoard";

const COPY = {
  en: { create: "New task", title: "Task title", body: "Page text (Markdown)", owner: "Responsible reference", kind: "Responsible type", kinds: ["Unassigned", "Person", "Agent", "System", "Other"], hint: "Assigning responsibility does not grant access or start execution.", context: "Context", next: "Next step", submit: "Create task", cancel: "Cancel", move: "Move to column", exists: "A page with this title already exists. Refresh the board to find it.", unknown: "Creation could not be confirmed. Refresh the board before trying again.", saved: "Task created in the wiki" },
  pt: { create: "Nova tarefa", title: "Título da tarefa", body: "Texto da página (Markdown)", owner: "Referência do responsável", kind: "Tipo de responsável", kinds: ["Não atribuído", "Pessoa", "Agente", "Sistema", "Outro"], hint: "Atribuir um responsável não concede acesso nem inicia a execução.", context: "Contexto", next: "Próximo passo", submit: "Criar tarefa", cancel: "Cancelar", move: "Mover para coluna", exists: "Já existe uma página com este título. Atualize o quadro para encontrá-la.", unknown: "Não foi possível confirmar a criação. Atualize o quadro antes de tentar novamente.", saved: "Tarefa criada na wiki" },
  es: { create: "Nueva tarea", title: "Título de la tarea", body: "Texto de la página (Markdown)", owner: "Referencia del responsable", kind: "Tipo de responsable", kinds: ["Sin asignar", "Persona", "Agente", "Sistema", "Otro"], hint: "Asignar responsabilidad no concede acceso ni inicia la ejecución.", context: "Contexto", next: "Próximo paso", submit: "Crear tarea", cancel: "Cancelar", move: "Mover a columna", exists: "Ya existe una página con este título. Actualiza el tablero para encontrarla.", unknown: "No se pudo confirmar la creación. Actualiza el tablero antes de reintentar.", saved: "Tarea creada en la wiki" }
};
export function pageEditorCopy(language: string) { return COPY[language.startsWith("pt") ? "pt" : language.startsWith("es") ? "es" : "en"]; }
const OWNER_KINDS = ["unassigned", "human", "agent", "system", "other"];
export function ActionPageFields({ title, body, ownerKind = "unassigned", ownerRef = "", language }: { title: string; body: string; ownerKind?: string; ownerRef?: string; language: string }) {
  const copy = pageEditorCopy(language);
  const [kind, setKind] = useState(ownerKind);
  const [ref, setRef] = useState(ownerRef);
  return <>
    <label>{copy.title}<input name="page_title" defaultValue={title} required maxLength={500} /></label>
    <label>{copy.body}<textarea name="page_body" defaultValue={body} maxLength={128000} rows={8} /></label>
    <label>{copy.kind}<select name="owner_kind" value={kind} onChange={e => { setKind(e.target.value); if (e.target.value === "unassigned") setRef(""); }}>{OWNER_KINDS.map((value, i) => <option key={value} value={value}>{copy.kinds[i]}</option>)}</select></label>
    <label>{copy.owner}<input name="owner_ref" value={ref} onChange={e => setRef(e.target.value)} disabled={kind === "unassigned"} required={kind !== "unassigned"} maxLength={500} /></label>
    <p className="boardProvenance">{copy.hint}</p>
  </>;
}
export function ActionCreateForm({ options, language, busy, cancel, submit }: { options: ActionCreationOptions; language: string; busy: boolean; cancel: () => void; submit: (input: ActionCreate) => void }) {
  const copy = pageEditorCopy(language);
  return <form className="boardForm boardCreate" aria-label={copy.create} onSubmit={event => {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    submit({ title: String(values.get("page_title")), body: String(values.get("page_body") || ""), context: String(values.get("context")), next_action: String(values.get("next_action")), owner_kind: String(values.get("owner_kind")), owner_ref: String(values.get("owner_ref") || "") });
  }}><h2>{copy.create}</h2><fieldset disabled={busy}>
    <ActionPageFields title="" body="" language={language} />
    <label>{copy.context}<select name="context" defaultValue={options.default_context}>{options.contexts.map(context => <option key={context}>{context}</option>)}</select></label>
    <label>{copy.next}<textarea name="next_action" required maxLength={2000} /></label>
    <div className="boardHeaderActions"><button type="button" onClick={cancel}>{copy.cancel}</button><button className="boardSave" type="submit">{copy.submit}</button></div>
  </fieldset></form>;
}
