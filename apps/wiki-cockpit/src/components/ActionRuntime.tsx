import { useEffect, useState } from "react";
import type { AdminPort } from "../application/ports";
import type { PageRecord } from "../types";
import type { CoordinationIndex, RuntimeProposal } from "../data/actionBoard";
import type { AdminPlan, AdminExecuteOutcome } from "../data/admin";
import { AdminPlanReview } from "./AdminPlanReview";
import { AdminUnlockDialog } from "./AdminUnlockDialog";
import { AdminStatusStrip } from "./AdminStatusStrip";

const COPY = {
  en: { title: "Execute this action", configure: "No runtime is configured for this coordinator. Integration must configure and verify this route first.",
    message: "Exact message to the executor", scope: "Only this message is sent. Wiki context is checked locally; page bodies are not exported.",
    dispatch: "Review dispatch", unlock: "Unlock local commands", inspect: "Reconcile existing run", receipt: "Result received — review and incorporation still required",
    pending: "The Gateway accepted the run. This is not task completion.", held: "Result preserved; current context must be reconciled before incorporation.",
    error: "Command unavailable. No retry was sent.", noRetry: "If a response is lost, refresh and reconcile the retained run. Do not submit the mission again.",
    result: "Executor result", prepare: "Prepare receipt proposal", incorporate: "Review wiki incorporation", close: "Close review",
    prepared: "Receipt committed on the proposal branch. Independent review and integration are still required.",
    received: "Receipt present on local main. This does not mark the action done or prove remote hosting.",
    reconcile: "The proposal changed. The integrator must reconcile the existing branch; do not prepare another receipt.",
    publish: "Review publication of this commit", draft: "Review opening its draft PR", promote: "Review integration of the reviewed PR",
    pr: "Existing PR number", reviewPath: "Independent review artifact path", reviewHash: "Review artifact SHA-256",
    reviewHelp: "The integrator supplies the existing independent review for this exact commit. This form does not issue approval on anyone's behalf.",
    publication: "Publication result received. Check the provider readback below.", merged: "PR integration verified by the provider. Refresh the approved checkout before treating its card as current.",
    adopt: "Review refresh of approved content", adopted: "Approved checkout updated. Reload the card to verify the received result.", reload: "Reload this card", review: "Open diff, gates and PR" },
  pt: { title: "Executar esta ação", configure: "Não há runtime configurado para este coordenador. O integrador precisa configurar e verificar a rota primeiro.",
    message: "Mensagem exata para o executor", scope: "Somente esta mensagem será enviada. O contexto da wiki é conferido localmente; o corpo das páginas não é exportado.",
    dispatch: "Revisar despacho", unlock: "Desbloquear comandos locais", inspect: "Reconciliar execução existente", receipt: "Resultado recebido — revisão e incorporação ainda necessárias",
    pending: "O Gateway aceitou a execução. Isso não conclui a tarefa.", held: "Resultado preservado; o contexto atual precisa ser reconciliado antes da incorporação.",
    error: "Comando indisponível. Nenhuma repetição foi enviada.", noRetry: "Se a resposta se perder, atualize e reconcilie a execução registrada. Não envie a missão novamente.",
    result: "Resultado do executor", prepare: "Preparar proposta de recebimento", incorporate: "Revisar incorporação na wiki", close: "Fechar revisão",
    prepared: "Recebimento commitado na branch de proposta. Ainda faltam revisão independente e integração.",
    received: "Recebimento presente na main local. Isso não conclui a ação nem comprova hospedagem remota.",
    reconcile: "A proposta mudou. O integrador deve reconciliar a branch existente; não preparar outro recebimento.",
    publish: "Revisar publicação deste commit", draft: "Revisar abertura da PR em rascunho", promote: "Revisar integração da PR revisada",
    pr: "Número da PR existente", reviewPath: "Caminho do parecer independente", reviewHash: "SHA-256 do parecer",
    reviewHelp: "O integrador fornece o parecer independente existente para este commit exato. Este formulário não emite aprovação em nome de ninguém.",
    publication: "Resultado da publicação recebido. Confira abaixo o recibo do provedor.", merged: "Integração da PR verificada no provedor. Atualize o checkout aprovado antes de tratar o card como atual.",
    adopt: "Revisar atualização do conteúdo aprovado", adopted: "Checkout aprovado atualizado. Recarregue o card para conferir o resultado recebido.", reload: "Recarregar este card", review: "Abrir diff, gates e PR" }
};

export function ActionRuntime({ admin, action, profile, attempts, recoveryError, disabled, language, refresh }: {
  admin: AdminPort; action: PageRecord; profile: CoordinationIndex["profiles"][number];
  attempts: NonNullable<CoordinationIndex["actions"][number]["runtime_attempts"]>;
  recoveryError?: string; disabled: boolean; language: string; refresh: () => void;
}) {
  const copy = COPY[language.startsWith("pt") ? "pt" : "en"];
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [unlock, setUnlock] = useState(false);
  const [plan, setPlan] = useState<AdminPlan | null>(null);
  const [notice, setNotice] = useState("");
  const [output, setOutput] = useState<Record<string, unknown> | null>(null);
  const [known, setKnown] = useState(attempts);
  const latest = [...attempts].sort((a,b) => b.attempted_at.localeCompare(a.attempted_at))[0];
  const [selectedEffect, setSelectedEffect] = useState(latest?.effect_key || "");
  const [proposal, setProposal] = useState<RuntimeProposal | null>(latest?.proposal || null);
  const [pr, setPr] = useState("");
  const [reviewPath, setReviewPath] = useState("");
  const [reviewHash, setReviewHash] = useState("");
  useEffect(() => {
    setKnown(items => [...attempts, ...items.filter(item => !attempts.some(a => a.effect_key === item.effect_key))]);
    const recovered = attempts.find(item => item.effect_key === selectedEffect);
    if (recovered) setProposal(recovered.proposal || null);
  }, [attempts, selectedEffect]);
  const configured = profile.runtime?.configured === true && !recoveryError;
  const request = async (command: string, params: Record<string, string>) => {
    if (busy || disabled || !configured) return;
    if (command === "agents.openclaw.inspect") {
      setSelectedEffect(params.effect_key);setOutput(null);
      setProposal(known.find(item => item.effect_key === params.effect_key)?.proposal || null);
      setPr("");setReviewPath("");setReviewHash("");
    }
    setBusy(true); setNotice("");
    try {
      const supplied = command.startsWith("agents.openclaw.") ? { profile: profile.id, action_id: action.id, ...params } : params;
      const result = await admin.planAdminCommand(command, supplied);
      if (result.ok) setPlan(result.plan);
      else setNotice(`${copy.error} (${result.detail || result.errorCode})`);
    } catch { setNotice(copy.error); }
    finally { setBusy(false); }
  };
  const executed = (outcome: AdminExecuteOutcome) => {
    if (!outcome.output || typeof outcome.output !== "object") return;
    const value = outcome.output as Record<string, unknown>;
    if (value.action_id !== action.id && !["wiki.proposal.publish", "wiki.proposal.promote", "wiki.proposal.adopt"].includes(outcome.commandId)) { setNotice(copy.error); return; }
    setOutput(value);
    if (outcome.commandId.startsWith("agents.openclaw.") && typeof value.effect_key === "string") {
      setSelectedEffect(value.effect_key);
      setKnown(items => items.some(item => item.effect_key === value.effect_key)
        ? items.map(item => item.effect_key === value.effect_key ? {...item,has_result:item.has_result || value.result_available === true} : item)
        : [...items, { effect_key: String(value.effect_key), attempted_at: "", has_result: value.result_available === true }]);
      if (outcome.commandId === "agents.openclaw.dispatch") setProposal(null);
    }
    if (value.proposal && typeof value.proposal === "object") setProposal(value.proposal as RuntimeProposal);
    if (outcome.commandId === "wiki.proposal.prepare" && value.prepared && typeof value.head === "string") {
      setProposal(p => p ? {...p, head: String(value.head), proposal_head: String(value.head), status: "prepared"} : null);
      setNotice(copy.prepared); return;
    }
    if (outcome.commandId === "wiki.proposal.publish") {
      if (typeof value.pr_url === "string") {const match=value.pr_url.match(/^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/([1-9][0-9]*)$/); if(match) setPr(match[1]);}
      setNotice(copy.publication); return;
    }
    if (outcome.commandId === "wiki.proposal.promote") {setNotice(copy.merged); return;}
    if (outcome.commandId === "wiki.proposal.adopt") {setNotice(copy.adopted); refresh(); return;}
    setNotice(value.integration_hold ? copy.held : value.result_available ? copy.receipt : copy.pending);
  };
  const result = output?.result && typeof output.result === "object" ? output.result as Record<string, unknown> : null;
  return <section className="boardRuntime" aria-label={copy.title}>
    <h3>{copy.title} · {profile.runtime?.label || "OpenClaw"}</h3>
    {!configured ? <p role="status">{recoveryError ? `${copy.error} (${recoveryError})` : copy.configure}</p> : <>
      <AdminStatusStrip lockAdminSession={admin.lockAdminSession} renewAdminSession={admin.renewAdminSession} onNotice={setNotice} />
      <button type="button" disabled={disabled || busy} onClick={() => setUnlock(true)}>{copy.unlock}</button>
      <p>{copy.scope}</p>
      <label>{copy.message}<textarea value={message} onChange={e => setMessage(e.target.value)} maxLength={12000} disabled={disabled || busy} /></label>
      <button type="button" disabled={disabled || busy || !message.trim() || Boolean(plan)} onClick={() => void request("agents.openclaw.dispatch", {
        action_sha256: action.content_sha256 || "", message
      })}>{copy.dispatch}</button>
      <p>{copy.noRetry}</p>
      <ul>{known.map(item => <li key={item.effect_key}><code>{item.effect_key}</code> {item.attempted_at}
        <button type="button" disabled={disabled || busy || Boolean(plan)} onClick={() => void request("agents.openclaw.inspect", {effect_key: item.effect_key})}>{copy.inspect}</button>
      </li>)}</ul>
    </>}
    {notice && <p role="status">{notice}</p>}
    {result && typeof result.text === "string" && <details open><summary>{copy.result}</summary><pre>{result.text}</pre></details>}
    {result && !output?.integration_hold && typeof output?.effect_key === "string" && <button type="button" disabled={disabled || busy || Boolean(plan)}
      onClick={() => void request("agents.openclaw.receipt", { effect_key: String(output.effect_key) })}>{copy.prepare}</button>}
    {proposal && <div className="boardRuntimeProposal">
      <code>{selectedEffect}</code>
      <p>{proposal.status === "prepared" ? copy.prepared : proposal.status === "received_in_main" ? copy.received : proposal.status === "awaiting_adoption" ? copy.adopt : proposal.status === "reconciliation_required" ? copy.reconcile : copy.incorporate}</p>
      <code>{proposal.branch} · {proposal.head}</code>
      <p><a href="/w?dock=approve">{copy.review}</a> · <button type="button" onClick={refresh}>{copy.reload}</button></p>
      {proposal.status === "material_ready" && <button type="button" disabled={disabled || busy || Boolean(plan)} onClick={() => void request("wiki.proposal.prepare", {
        material_path: proposal.material_path, material_sha256: proposal.material_sha256
      })}>{copy.incorporate}</button>}
      {proposal.status === "prepared" && <>
        <button type="button" disabled={disabled || busy || Boolean(plan)} onClick={() => void request("wiki.proposal.publish", {expected_head: proposal.head, operation: "publish_proposal"})}>{copy.publish}</button>
        <button type="button" disabled={disabled || busy || Boolean(plan)} onClick={() => void request("wiki.proposal.publish", {
          expected_head: proposal.head, operation: "open_draft_pr", title: `Receive runtime result for ${action.id}`,
          body: `Receive the retained execution result on ${action.id}. This preserves action state and factual content. Independent review and normal gates remain required.`
        })}>{copy.draft}</button>
        <details><summary>{copy.promote}</summary><p>{copy.reviewHelp}</p>
          <label>{copy.reviewPath}<input value={reviewPath} onChange={e => setReviewPath(e.target.value)} /></label>
          <label>{copy.reviewHash}<input value={reviewHash} onChange={e => setReviewHash(e.target.value)} /></label>
          <button type="button" disabled={disabled || busy || Boolean(plan) || !/^[1-9][0-9]*$/.test(pr) || !reviewPath || !/^[0-9a-f]{64}$/.test(reviewHash)} onClick={() => void request("wiki.proposal.promote", {
            expected_head: proposal.head, approved_base: proposal.approved_base, pr, review_path: reviewPath, review_sha256: reviewHash
          })}>{copy.promote}</button>
        </details>
      </>}
      {["prepared", "awaiting_adoption"].includes(proposal.status) && <div>
        <label>{copy.pr}<input value={pr} onChange={e => setPr(e.target.value)} inputMode="numeric" /></label>
        <button type="button" disabled={disabled || busy || Boolean(plan) || !/^[1-9][0-9]*$/.test(pr)} onClick={() => void request("wiki.proposal.adopt", {
          expected_head: proposal.head, proposal_head: proposal.proposal_head, pr
        })}>{copy.adopt}</button>
      </div>}
    </div>}
    {unlock && <AdminUnlockDialog requestAdminChallenge={admin.requestAdminChallenge} unlockAdminSession={admin.unlockAdminSession}
      onUnlocked={() => {setUnlock(false); setNotice("");}} onClose={() => setUnlock(false)} />}
    {plan && <AdminPlanReview plan={plan} executeAdminPlan={admin.executeAdminPlan} executionBlocked={disabled}
      onExecuted={executed} onNotice={setNotice} onClose={() => {setPlan(null); if (!output) refresh();}} />}
  </section>;
}
