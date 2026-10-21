import { useEffect, useRef, useState } from "react";
import { t } from "../data/i18n";
import type { SourceEntity, SourceExecutionBinding } from "../types";
import type { SourceHostPort, ExecutorRoute, HostResult, NativeReadReceipt } from "../application/sourceAccess";

export function SourceExecutorSetup({ source, demo, onBind, createHost }: {source: SourceEntity; demo: boolean; createHost?: () => SourceHostPort; onBind: (execution: SourceExecutionBinding) => void}) {
  const bridge = useRef<SourceHostPort>();
  const [routes, setRoutes] = useState<ExecutorRoute[]>([]);
  const [routeKey, setRouteKey] = useState("");
  const [inspection, setInspection] = useState<HostResult>();
  const [method, setMethod] = useState<SourceExecutionBinding["method"]>(source.access_policy?.execution?.method || (source.source_kind === "repository" ? "local_git" : "mcp"));
  const [provider, setProvider] = useState(source.access_policy?.execution?.provider_id || "");
  const [accountId, setAccountId] = useState(source.access_policy?.execution?.account_id || "");
  const [receipts, setReceipts] = useState<NativeReadReceipt[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readUnknown, setReadUnknown] = useState(false);
  const [reconciled, setReconciled] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const generation = useRef(0);
  useEffect(() => {
    generation.current += 1; bridge.current?.close(); bridge.current = undefined;
    setRoutes([]); setRouteKey(""); setInspection(undefined); setReceipts([]); setError(""); setReconciled(false); setBusy(false); setReadUnknown(false); setReconciled(false);
    setMethod(source.access_policy?.execution?.method || (source.source_kind === "repository" ? "local_git" : "mcp"));
    setProvider(source.access_policy?.execution?.provider_id || ""); setAccountId(source.access_policy?.execution?.account_id || "");
    return () => { generation.current += 1; bridge.current?.close(); };
  }, [source.source_id, source.access?.binding_sha256]);
  const route = routes.find(r => r.key === routeKey);
  const currentExecution = source.access_policy?.execution;
  const account = inspection?.accounts?.find(a=>a.id===accountId && a.connector===provider);
  const managedAccount = method === "managed_connector";
  const bound = currentExecution && route && currentExecution.connection_id === route.connectionId && currentExecution.profile === route.profile && currentExecution.target_profile === route.targetProfile && currentExecution.method === method && currentExecution.provider_id === provider && (!managedAccount || Boolean(account && currentExecution.account_id === account.id && currentExecution.account_alias === account.alias));
  const run = async (action: "routes" | "inspect" | "configure" | "read_test" | "read_receipts") => {
    if (demo || busy) return;
    const epoch = generation.current; setBusy(true); setError("");
    try {
      if (!bridge.current) { if (!createHost) throw new Error("executor_unavailable"); const client = createHost(); bridge.current = client; await client.connect(); }
      const result = await bridge.current.request(source, action, action === "routes" ? undefined : routeKey, inspection?.binding?.config_sha256, action === "configure" ? method : undefined);
      if (epoch !== generation.current) return;
      if (action === "routes") {
        setRoutes(result.routes || []);
        const match = result.routes?.find(r => r.connectionId === currentExecution?.connection_id && r.profile === currentExecution?.profile && r.targetProfile === currentExecution?.target_profile);
        setRouteKey(match?.key || "");
      } else if (action === "inspect") { setInspection(result); setReceipts([]); setReconciled(false); }
      else if (action === "read_test") { setReceipts([result as NativeReadReceipt]); setReadUnknown(result.status === "pending"); if (result.status === "pending") setError("source_read_result_unknown"); }
      else if (action === "read_receipts") { setReceipts(result.receipts || []); const unresolved = Boolean(result.unresolved_request) || (result.receipts || []).some(r => r.status === "pending"); setReadUnknown(unresolved); if (unresolved) setError("source_read_result_unknown"); setReconciled(true); }
    } catch (cause) {
      if (epoch !== generation.current) return;
      const code = cause instanceof Error ? cause.message : "executor_unavailable";
      setError(code); if (code === "source_read_result_unknown") { setReadUnknown(true); setReconciled(false); }
      if (action === "routes") { bridge.current?.close(); bridge.current = undefined; }
    } finally { if (epoch === generation.current) setBusy(false); }
  };
  const sameExecution = (a: typeof currentExecution, b: typeof currentExecution) => Boolean(a && b && (["connection_id", "profile", "target_profile", "method", "provider_id", "resource_ref", "account_id", "account_alias"] as const).every(k => a[k] === b[k]));
  const visible = receipts.filter(r => r.source_id === source.source_id && r.binding_sha256 === source.access?.binding_sha256 && r.config_sha256 === inspection?.binding?.config_sha256 && sameExecution(r.execution, currentExecution));
  return <section className="sourceAuthorizationCard" aria-label={t("source.executor.title")}>
    <h4>{t("source.executor.title")}</h4><p>{t("source.executor.intro")}</p>
    <button type="button" className="secondaryButton" disabled={demo || busy} onClick={() => void run("routes")}>{t("source.executor.discover")}</button>
    <label>{t("source.executor.route")}<select value={routeKey} disabled={busy || !routes.length} onChange={e => { setRouteKey(e.target.value); setInspection(undefined); setReceipts([]); setError(""); setReconciled(false); }}>
      <option value="">{t("source.executor.choose")}</option>
      {routes.map(r => <option key={r.key} value={r.key}>{r.connectionId} / {r.profile} → {r.targetProfile}</option>)}
    </select></label>
    <button type="button" className="secondaryButton" disabled={!route || busy || demo} onClick={() => void run("inspect")}>{t("source.executor.inspect")}</button>
    {inspection && <>
      <p>{t("source.executor.support", { managed: inspection.managed_available ? t("source.executor.available") : t("source.executor.unavailable"), mcp: String(inspection.providers?.filter(p=>p.method==='mcp').length || 0) })}</p>
      <p>{t("source.executor.catalogBoundary")}</p>
      {inspection.support_errors?.filter((code): code is string => Boolean(code)).map((code,i)=><p role="alert" key={i}>{t(`source.executor.error.${code}`)}</p>)}
      <label>{t("source.executor.method")}<select value={method} disabled={busy} onChange={e=>{setMethod(e.target.value as typeof method);setProvider("");setReceipts([]);}}>
        {source.source_kind === "repository" && <option value="local_git">{t("source.executor.localGit")}</option>}
        <option value="mcp">MCP</option><option value="managed_connector">{t("source.executor.managed")}</option><option value="browser_controller">{t("source.executor.browser")}</option>
      </select></label>
      {method === "local_git" && <p>{t("source.executor.resource")}: {inspection.binding?.resource_options?.find(r=>r.id==='wiki_repository')?.target || t("source.executor.unsupportedResource")} · git.metadata.read</p>}
      {method !== "local_git" && method !== "browser_controller" && <label>{t("source.executor.provider")}<select value={provider} disabled={busy} onChange={e=>setProvider(e.target.value)}>
        <option value="">{t("source.executor.choose")}</option>
        {inspection.providers?.filter(p=>p.method===method).map(p=><option key={p.id} value={p.id}>{p.label}</option>)}
      </select></label>}
      {managedAccount && <label>{t("source.executor.account")}<select value={accountId} disabled={busy} onChange={e=>{setAccountId(e.target.value);setReceipts([]);setReconciled(false);}}>
        <option value="">{t("source.executor.choose")}</option>
        {inspection.accounts?.filter(a=>a.connector===provider).map(a=><option key={a.id} value={a.id}>{a.label} / {a.alias} · {a.status}</option>)}
      </select></label>}
      <div className="sourceUpdateActions">
        {(method === "managed_connector" || method === "mcp" || method === "browser_controller") && <button type="button" className="secondaryButton" disabled={!route || busy || demo} onClick={() => void run("configure")}>{t("source.executor.configureOfficial")}</button>}
        <button type="button" className="secondaryButton" disabled={!route || busy || demo || (method !== "local_git" ? !provider || (managedAccount && !account) : !inspection.binding?.resource_options?.some(r=>r.id==="wiki_repository"))} onClick={() => route && onBind({connection_id:route.connectionId,profile:route.profile,target_profile:route.targetProfile,method,provider_id:provider,resource_ref:method==='local_git'?'wiki_repository':'',...(managedAccount && account ? {account_id:account.id,account_alias:account.alias}:{})})}>{t("source.executor.bind")}</button>
        <button type="button" className="secondaryButton" disabled={!bound || busy || demo || readUnknown || !reconciled} onClick={() => void run("read_test")}>{t("source.executor.testRead")}</button>
        <button type="button" className="secondaryButton" disabled={!bound || busy || demo} onClick={() => void run("read_receipts")}>{t("source.executor.receipts")}</button>
      </div>
      {!bound && <p>{t("source.executor.saveFirst")}</p>}
      {bound && !reconciled && <p>{t("source.executor.reconcileFirst")}</p>}
      {method === "browser_controller" && <p>{t("source.executor.browserRecovery", { profile: route?.profile || "" })}</p>}
      {method !== "local_git" && <p>{t(managedAccount && source.platform === "gmail" && source.source_kind === "account" && provider === "gmail" ? "source.executor.gmailSupport" : "source.executor.readSupport")}</p>}
    </>}
    {error && <p role="alert">{t(`source.executor.error.${error}`)}</p>}
    {visible.map((receipt,i)=><article key={i}>
      <strong>{t(`source.executor.receipt.${receipt.status === "read_verified" && (!receipt.valid_until || !Number.isFinite(Date.parse(receipt.valid_until)) || Date.parse(receipt.valid_until) <= now) ? "expired" : receipt.status}`)}</strong>
      <p>{receipt.checked_at} · PID {receipt.executor_pid} · {t("source.executor.identity")}: {receipt.identity?.status || "unknown"} {receipt.identity?.confirmed_identity || ""}</p>
      <p>{t("source.executor.permissions")}: {receipt.observed_permissions?.join(", ") || "—"}</p>
      {receipt.error_code && <p>{t(`source.executor.error.${receipt.error_code}`)}</p>}
      <p>{t("source.executor.noWriteProof")}</p>
    </article>)}
  </section>;
}
