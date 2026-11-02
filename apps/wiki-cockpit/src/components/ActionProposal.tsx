import { useState } from "react";
import type { AdminPort } from "../application/ports";
import type { WorkProposal } from "../data/actionBoard";
import type { AdminPlan, AdminExecuteOutcome } from "../data/admin";
import { AdminPlanReview } from "./AdminPlanReview";
import { AdminUnlockDialog } from "./AdminUnlockDialog";
import { AdminStatusStrip } from "./AdminStatusStrip";
import { PreparatoryObservations } from "./PreparatoryObservations";

const COPY = {
  en: { title: "Proposal and integration", scope: "Select existing proposal material in this checkout. An administrative session enables command review; each effect still requires its own reviewed plan and current authority.", material: "Proposal material path", hash: "Material SHA-256", prepare: "Review proposal preparation", unlock: "Unlock local commands", error: "Command unavailable. Check its scope and retained evidence before trying again.", prepared: "Proposal committed locally. Independent review and integration are still required.", received: "Receipt present on local main. Content incorporation and external effects require their own evidence.", reconcile: "The proposal changed. The integrator must reconcile the existing branch.", review: "Open diff, gates and PR", reload: "Reload this card", publish: "Review publication of this commit", draft: "Review opening its draft PR", promote: "Review integration of the reviewed PR", adopt: "Review refresh of approved content", adopted: "Approved checkout updated. Reload the card to verify its content.", published: "Publication response received. Check the provider readback.", merged: "PR integration verified by the provider. Refresh the approved checkout to read its content.", pr: "Existing PR number", reviewPath: "Independent review artifact path", reviewHash: "Review artifact SHA-256", reviewHelp: "Supply an existing independent review for this exact commit. This form does not issue approval.", result: "Command readback" },
  pt: { title: "Proposta e integração", scope: "Selecione material de proposta existente neste checkout. A sessão administrativa habilita a revisão de comandos; cada efeito ainda exige plano revisado e autoridade vigente.", material: "Caminho do material da proposta", hash: "SHA-256 do material", prepare: "Revisar preparação da proposta", unlock: "Desbloquear comandos locais", error: "Comando indisponível. Confira o escopo e as evidências preservadas antes de tentar novamente.", prepared: "Proposta commitada localmente. Ainda faltam revisão independente e integração.", received: "Recibo presente na main local. Incorporação do conteúdo e efeitos externos exigem evidências próprias.", reconcile: "A proposta mudou. O integrador precisa reconciliar a branch existente.", review: "Abrir diff, gates e PR", reload: "Recarregar este card", publish: "Revisar publicação deste commit", draft: "Revisar abertura da PR em rascunho", promote: "Revisar integração da PR revisada", adopt: "Revisar atualização do conteúdo aprovado", adopted: "Checkout aprovado atualizado. Recarregue o card para conferir o conteúdo.", published: "Resposta da publicação recebida. Confira o recibo do provedor.", merged: "Integração da PR verificada no provedor. Atualize o checkout aprovado para ler o conteúdo.", pr: "Número da PR existente", reviewPath: "Caminho do parecer independente", reviewHash: "SHA-256 do parecer", reviewHelp: "Forneça um parecer independente existente para este commit exato. Este formulário não emite aprovação.", result: "Resultado do comando" },
  es: { title: "Propuesta e integración", scope: "Seleccione material de propuesta existente en este checkout. La sesión administrativa permite revisar comandos; cada efecto requiere su propio plan revisado y autoridad vigente.", material: "Ruta del material de propuesta", hash: "SHA-256 del material", prepare: "Revisar preparación de propuesta", unlock: "Desbloquear comandos locales", error: "Comando no disponible. Revise el alcance y la evidencia conservada antes de reintentar.", prepared: "Propuesta confirmada localmente. Faltan revisión independiente e integración.", received: "Recibo presente en main local. La incorporación de contenido y los efectos externos requieren evidencia propia.", reconcile: "La propuesta cambió. El integrador debe conciliar la rama existente.", review: "Abrir diff, gates y PR", reload: "Recargar esta tarjeta", publish: "Revisar publicación de este commit", draft: "Revisar apertura de PR borrador", promote: "Revisar integración de la PR revisada", adopt: "Revisar actualización del contenido aprobado", adopted: "Checkout aprobado actualizado. Recargue la tarjeta para verificar su contenido.", published: "Respuesta de publicación recibida. Revise el recibo del proveedor.", merged: "Integración de PR verificada por el proveedor. Actualice el checkout aprobado para leer su contenido.", pr: "Número de PR existente", reviewPath: "Ruta de revisión independiente", reviewHash: "SHA-256 de la revisión", reviewHelp: "Proporcione una revisión independiente existente para este commit exacto. Este formulario no concede aprobación.", result: "Resultado del comando" }
};

function proposalFrom(value: unknown): WorkProposal | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (!["material_ready", "prepared", "received_in_main", "awaiting_adoption", "reconciliation_required"].includes(String(row.status)) ||
    !["head", "proposal_head", "approved_base", "branch", "material_path", "material_sha256"].every(key => typeof row[key] === "string")) return null;
  return row as WorkProposal;
}

export function ActionProposal({ admin, actionId, disabled, language, refresh, initialProposal = null }: {
  admin: AdminPort; actionId: string; disabled: boolean; language: string; refresh: () => void; initialProposal?: WorkProposal | null;
}) {
  const copy = COPY[language.startsWith("pt") ? "pt" : language.startsWith("es") ? "es" : "en"];
  const [material, setMaterial] = useState("");
  const [hash, setHash] = useState("");
  const [busy, setBusy] = useState(false);
  const [unlock, setUnlock] = useState(false);
  const [plan, setPlan] = useState<AdminPlan | null>(null);
  const [notice, setNotice] = useState("");
  const [observations, setObservations] = useState<string[]>([]);
  const [output, setOutput] = useState<Record<string, unknown> | null>(null);
  const [proposal, setProposal] = useState<WorkProposal | null>(initialProposal);
  const [pr, setPr] = useState("");
  const [reviewPath, setReviewPath] = useState("");
  const [reviewHash, setReviewHash] = useState("");
  const blocked = disabled || busy || Boolean(plan);
  const request = async (command: string, params: Record<string, string>) => {
    if (blocked) return;
    setBusy(true); setNotice(""); setObservations([]);
    try {
      const result = await admin.planAdminCommand(command, params);
      if (result.ok && result.plan.commandId === command) setPlan(result.plan);
      else if (!result.ok) { setNotice(`${copy.error} (${result.detail || result.errorCode})`); setObservations(result.preparatoryObservations || []); }
      else setNotice(copy.error);
    } catch { setNotice(copy.error); }
    finally { setBusy(false); }
  };
  const executed = (outcome: AdminExecuteOutcome) => {
    if (!plan || outcome.commandId !== plan.commandId || outcome.planId !== plan.planId || outcome.status !== "success" || outcome.dryRun || !outcome.output || typeof outcome.output !== "object") return;
    const value = outcome.output as Record<string, unknown>;
    setOutput(value);
    const observed = proposalFrom(value.proposal);
    if (observed) setProposal(observed);
    if (outcome.commandId === "wiki.proposal.prepare" && value.prepared && typeof value.head === "string") {
      setProposal(p => observed || (p ? { ...p, head: String(value.head), proposal_head: String(value.head), status: "prepared" } : null));
      setNotice(copy.prepared);
    } else if (outcome.commandId === "wiki.proposal.publish") {
      if (typeof value.pr_url === "string") { const match = value.pr_url.match(/^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/([1-9][0-9]*)$/); if (match) setPr(match[1]); }
      setNotice(copy.published);
    } else if (outcome.commandId === "wiki.proposal.promote") setNotice(copy.merged);
    else if (outcome.commandId === "wiki.proposal.adopt") { setNotice(copy.adopted); refresh(); }
  };
  return <section className="boardProposal" aria-label={copy.title}>
    <h3>{copy.title}</h3><p>{copy.scope}</p>
    <AdminStatusStrip lockAdminSession={admin.lockAdminSession} renewAdminSession={admin.renewAdminSession} onNotice={setNotice} />
    <button type="button" disabled={disabled || busy} onClick={() => setUnlock(true)}>{copy.unlock}</button>
    {!proposal && <><label>{copy.material}<input value={material} onChange={e => setMaterial(e.target.value)} disabled={blocked} /></label>
      <label>{copy.hash}<input value={hash} onChange={e => setHash(e.target.value)} disabled={blocked} /></label>
      <button type="button" disabled={blocked || !material.trim() || !/^[0-9a-f]{64}$/.test(hash)} onClick={() => void request("wiki.proposal.prepare", { material_path: material, material_sha256: hash })}>{copy.prepare}</button></>}
    {notice && <p role="status">{notice}</p>}
    <PreparatoryObservations observations={observations} />
    {output && <details><summary>{copy.result}</summary><pre>{JSON.stringify(output, null, 2)}</pre></details>}
    {proposal && <div className="boardProposalDetails">
      <p>{proposal.status === "prepared" ? copy.prepared : proposal.status === "received_in_main" ? copy.received : proposal.status === "reconciliation_required" ? copy.reconcile : copy.adopt}</p>
      <code>{proposal.branch} · {proposal.head}</code>
      <p><a href="/w?dock=approve">{copy.review}</a> · <button type="button" onClick={refresh}>{copy.reload}</button></p>
      {proposal.status === "material_ready" && <button type="button" disabled={blocked} onClick={() => void request("wiki.proposal.prepare", { material_path: proposal.material_path, material_sha256: proposal.material_sha256 })}>{copy.prepare}</button>}
      {proposal.status === "prepared" && <>
        <button type="button" disabled={blocked} onClick={() => void request("wiki.proposal.publish", { expected_head: proposal.head, operation: "publish_proposal" })}>{copy.publish}</button>
        <button type="button" disabled={blocked} onClick={() => void request("wiki.proposal.publish", { expected_head: proposal.head, operation: "open_draft_pr", title: `Proposal for ${actionId}`, body: `Review the proposal associated with ${actionId}. Independent review and normal gates remain required.` })}>{copy.draft}</button>
        <details><summary>{copy.promote}</summary><p>{copy.reviewHelp}</p>
          <label>{copy.reviewPath}<input value={reviewPath} onChange={e => setReviewPath(e.target.value)} /></label>
          <label>{copy.reviewHash}<input value={reviewHash} onChange={e => setReviewHash(e.target.value)} /></label>
          <button type="button" disabled={blocked || !/^[1-9][0-9]*$/.test(pr) || !reviewPath || !/^[0-9a-f]{64}$/.test(reviewHash)} onClick={() => void request("wiki.proposal.promote", { expected_head: proposal.head, approved_base: proposal.approved_base, pr, review_path: reviewPath, review_sha256: reviewHash })}>{copy.promote}</button>
        </details>
      </>}
      {["prepared", "awaiting_adoption"].includes(proposal.status) && <div>
        <label>{copy.pr}<input value={pr} onChange={e => setPr(e.target.value)} inputMode="numeric" /></label>
        <button type="button" disabled={blocked || !/^[1-9][0-9]*$/.test(pr)} onClick={() => void request("wiki.proposal.adopt", { expected_head: proposal.head, proposal_head: proposal.proposal_head, pr })}>{copy.adopt}</button>
      </div>}
    </div>}
    {unlock && <AdminUnlockDialog requestAdminChallenge={admin.requestAdminChallenge} unlockAdminSession={admin.unlockAdminSession} onUnlocked={() => { setUnlock(false); setNotice(""); }} onClose={() => setUnlock(false)} />}
    {plan && <AdminPlanReview plan={plan} executeAdminPlan={admin.executeAdminPlan} executionBlocked={disabled} onExecuted={executed} onNotice={setNotice} onClose={() => setPlan(null)} />}
  </section>;
}
