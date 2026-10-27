import { useState } from "react";
import type { PageRecord, ResolvedLink } from "../types";
import { EvidenceMarkdown } from "./EvidenceMarkdown";
import { isLocalSummaryReference, readableMessage } from "../data/boardPresentation";
import { isDialogueHistory, type DialogueInput } from "../data/actionBoard";

const COPY = {
  pt: { invalid: "Histórico de conversa inválido. Revise a página original antes de responder.", title: "Conversa desta ação", empty: "Nenhuma mensagem registrada.", pending: "perguntas aguardando resposta", answer: "Responder", question: "Fazer pergunta", confirm: "Pedir confirmação", comment: "Acrescentar informação", text: "Mensagem", send: "Registrar no card", operator: "Você", original: "Registro original e detalhes", localSummary: "Referência de resumo local registrada. Consulte os artefatos relacionados para ler o resultado.", waiting: "Histórico registrado na wiki. Estas mensagens não indicam a atividade atual do executor.", replied: "Resposta registrada", kind: "Tipo de mensagem", direction: "Direção", cancel: "Cancelar resposta", confirmation: "Uma resposta esclarece esta pergunta; não concede autorização geral nem remove outros bloqueios." },
  en: { invalid: "Invalid conversation history. Review the original page before replying.", title: "Action conversation", empty: "No messages recorded.", pending: "questions awaiting an answer", answer: "Reply", question: "Ask a question", confirm: "Request confirmation", comment: "Add information", text: "Message", send: "Record on card", operator: "You", original: "Original record and details", localSummary: "Local summary reference recorded. Consult related artifacts to read the result.", waiting: "History recorded in the wiki. These messages do not indicate current executor activity.", replied: "Answer recorded", kind: "Message type", direction: "Direction", cancel: "Cancel reply", confirmation: "An answer clarifies this question; it grants no blanket authorization and removes no other blockers." },
  es: { invalid: "Historial de conversación inválido. Revise la página original antes de responder.", title: "Conversación de esta acción", empty: "No hay mensajes registrados.", pending: "preguntas esperando respuesta", answer: "Responder", question: "Hacer pregunta", confirm: "Pedir confirmación", comment: "Añadir información", text: "Mensaje", send: "Registrar en la tarjeta", operator: "Tú", original: "Registro original y detalles", localSummary: "Referencia de resumen local registrada. Consulta los artefactos relacionados para leer el resultado.", waiting: "Historial registrado en la wiki. Estos mensajes no indican la actividad actual del ejecutor.", replied: "Respuesta registrada", kind: "Tipo de mensaje", direction: "Dirección", cancel: "Cancelar respuesta", confirmation: "Una respuesta aclara esta pregunta; no concede autorización general ni elimina otros bloqueos." }
};
export function ActionDialogue({ events, coordinator, coordinatorLabel, pages = [], links = [], open = () => {}, language, writable, busy, send }: {
  events: unknown; coordinator?: string; coordinatorLabel?: string; pages?: PageRecord[]; language: string; writable: boolean; busy: boolean;
  links?: ResolvedLink[]; open?: (id: string) => void;
  send: (event: DialogueInput) => Promise<boolean>;
}) {
  const copy = COPY[language.startsWith("pt") ? "pt" : language.startsWith("es") ? "es" : "en"];
  const [kind, setKind] = useState<DialogueInput["kind"]>("comment");
  const [text, setText] = useState(""); const [reply, setReply] = useState("");
  if (!isDialogueHistory(events)) return <section className="boardDialogue"><h3>{copy.title}</h3><p role="alert">{copy.invalid}</p></section>;
  const answered = new Set(events.filter(e => e.kind === "answer").map(e => e.reply_to));
  const questions = events.filter(e => ["question", "confirmation_request"].includes(e.kind));
  const labels = { direction: copy.direction, question: copy.question, confirmation_request: copy.confirm, answer: copy.replied, comment: copy.comment };
  return <section className="boardDialogue"><h3>{copy.title}</h3>
    {questions.some(e => !answered.has(e.event_id)) && <p role="status">{questions.filter(e => !answered.has(e.event_id)).length} {copy.pending}</p>}
    {!events.length && <p>{copy.empty}</p>}
    <ol>{events.map(e => <li key={e.event_id}><strong>{e.actor === "operator" ? copy.operator : e.actor === `coordinator:${coordinator}` && coordinatorLabel ? coordinatorLabel : e.actor} · {labels[e.kind]}</strong><small>{e.at}</small>{e.reply_to && <blockquote>{readableMessage(events.find(q => q.event_id === e.reply_to)?.text || "", pages)}</blockquote>}{isLocalSummaryReference(e.text) ? <p>{copy.localSummary}</p> : <EvidenceMarkdown text={e.text} links={links} open={open} pages={pages} language={language} />}<details className="boardOriginal"><summary>{copy.original}</summary><p>{e.text}</p><pre>{JSON.stringify(e, null, 2)}</pre></details>{["question", "confirmation_request"].includes(e.kind) && (answered.has(e.event_id) ? <small>{copy.replied}</small> : e.actor !== "operator" && writable && coordinator === e.coordinator && <button disabled={busy} onClick={() => { setReply(e.event_id); setKind("answer"); }}>{copy.answer}</button>)}</li>)}</ol>
    {coordinator && writable && <form onSubmit={e => { e.preventDefault(); if (!busy && text.trim()) void send({ event_id: crypto.randomUUID(), kind, text: text.trim(), coordinator, reply_to: reply }).then(ok => { if (ok) { setText(""); setReply(""); setKind("comment"); } }); }}><fieldset disabled={busy}>
      {reply ? <><blockquote>{readableMessage(events.find(e => e.event_id === reply)?.text || "", pages)}</blockquote><button type="button" onClick={() => { setReply(""); setKind("comment"); }}>{copy.cancel}</button></> : <label>{copy.kind}<select value={kind} onChange={e => setKind(e.target.value as DialogueInput["kind"])}><option value="comment">{copy.comment}</option><option value="question">{copy.question}</option><option value="confirmation_request">{copy.confirm}</option></select></label>}
      <label>{copy.text}<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={2000} /></label><button type="submit">{copy.send}</button>
    </fieldset><p>{copy.confirmation}</p></form>}
    {events.length > 0 && <p className="boardProvenance">{copy.waiting}</p>}
  </section>;
}
