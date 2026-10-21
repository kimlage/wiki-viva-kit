import { useEffect, useRef, useState } from "react";
import { t } from "../data/i18n";
import type { SourceEntity, SourceExecutionBinding } from "../types";
import type { SourceHostPort, ExecutorRoute, HostResult, NativeReadReceipt, HostAction } from "../application/sourceAccess";

export function SourceExecutorSetup({ source, demo, onBind, createHost }: {source: SourceEntity; demo: boolean; createHost?: () => SourceHostPort; onBind: (execution: SourceExecutionBinding) => void}) {
  const bridge=useRef<SourceHostPort>();
  const [routes,setRoutes]=useState<ExecutorRoute[]>([]);
  const [routeKey,setRouteKey]=useState("");
  const [inspection,setInspection]=useState<HostResult>();
  const current=source.access_policy?.execution;
  const [storedId,setStoredId]=useState(current?.stored_session_id || "");
  const [accountId,setAccountId]=useState(current?.account_id || "");
  const [setupMethod,setSetupMethod]=useState("mcp");
  const [receipts,setReceipts]=useState<NativeReadReceipt[]>([]);
  const [activity,setActivity]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [unknown,setUnknown]=useState(false);
  const [reconciled,setReconciled]=useState(false);
  const generation=useRef(0);
  useEffect(()=>{
    generation.current++;bridge.current?.close();bridge.current=undefined;
    setRoutes([]);setRouteKey("");setInspection(undefined);setStoredId(current?.stored_session_id || "");setAccountId(current?.account_id || "");
    setReceipts([]);setBusy(false);setError("");setUnknown(false);setReconciled(false);setActivity(false);
    return ()=>{generation.current++;bridge.current?.close();};
  },[source.source_id,source.access?.binding_sha256]);
  const route=routes.find(r=>r.key===routeKey);
  const account=inspection?.accounts?.find(a=>a.id===accountId);
  const bound=Boolean(current && route && current.connection_id===route.connectionId && current.profile===route.profile && current.target_profile===route.targetProfile && current.stored_session_id===storedId &&
    (current.account_id ? account?.id===current.account_id && account.alias===current.account_alias && account.connector===current.provider_id : !accountId));
  const run=async(action:HostAction)=>{
    if(demo || busy)return;
    const epoch=generation.current;setBusy(true);setError("");
    try {
      if(!bridge.current){if(!createHost)throw new Error("executor_unavailable");bridge.current=createHost();bridge.current.subscribeActivity?.(()=>{if(epoch===generation.current)setActivity(true);});await bridge.current.connect();}
      const result=await bridge.current.request(source,action,action==='routes'?undefined:routeKey,
        action==='routes'||action==='inspect'?undefined:inspection?.binding?.config_sha256,action==='configure'?setupMethod:undefined);
      if(epoch!==generation.current)return;
      if(action==='routes'){
        setRoutes(result.routes || []);
        setRouteKey(result.routes?.find(r=>r.connectionId===current?.connection_id && r.profile===current?.profile && r.targetProfile===current?.target_profile)?.key || "");
      }else if(action==='inspect'){setInspection(result);setReceipts([]);setReconciled(false);}
      else if(action==='read_test'){setReceipts([result as NativeReadReceipt]);setUnknown(['pending','submitted'].includes(result.status || ''));}
      else if(action==='read_receipts'){
        setActivity(false);setReceipts(result.receipts || []);setUnknown(Boolean(result.unresolved_request)||(result.receipts || []).some(r=>['pending','submitted'].includes(r.status)));setReconciled(true);
      }
    }catch(cause){if(epoch===generation.current){const code=cause instanceof Error?cause.message:'executor_unavailable';setError(code);if(code==='source_read_result_unknown'){setUnknown(true);setReconciled(false);}}}
    finally{if(epoch===generation.current)setBusy(false);}
  };
  const same=(a:typeof current,b:typeof current)=>Boolean(a&&b&&(['connection_id','profile','target_profile','stored_session_id','provider_id','account_id','account_alias'] as const).every(k=>a[k]===b[k]));
  const visible=receipts.filter(r=>r.source_id===source.source_id && r.binding_sha256===source.access?.binding_sha256 && r.config_sha256===inspection?.binding?.config_sha256 && same(r.execution,current));
  return <section className="sourceAuthorizationCard" aria-label={t('source.executor.title')}>
    <h4>{t('source.executor.title')}</h4><p>{t('source.executor.nativeIntro')}</p>
    <button type="button" className="secondaryButton" disabled={demo||busy} onClick={()=>void run('routes')}>{t('source.executor.discover')}</button>
    <label>{t('source.executor.route')}<select value={routeKey} disabled={busy||!routes.length} onChange={e=>{setRouteKey(e.target.value);setInspection(undefined);setReceipts([]);setReconciled(false);}}>
      <option value="">{t('source.executor.choose')}</option>{routes.map(r=><option key={r.key} value={r.key}>{r.connectionId} / {r.profile} → {r.targetProfile}</option>)}
    </select></label>
    <button type="button" className="secondaryButton" disabled={!route||busy||demo} onClick={()=>void run('inspect')}>{t('source.executor.inspect')}</button>
    {inspection&&<>
      <p>{t('source.executor.catalogBoundary')}</p>
      {inspection.support_errors?.filter((e):e is string=>Boolean(e)).map((e,i)=><p role="alert" key={i}>{t(`source.executor.error.${e}`)}</p>)}
      <label>{t('source.executor.nativeSession')}<select value={storedId} disabled={busy} onChange={e=>{setStoredId(e.target.value);setReconciled(false);setReceipts([]);}}>
        <option value="">{t('source.executor.choose')}</option>
        {current?.stored_session_id && !inspection.sessions?.some(s=>s.id===current.stored_session_id) && <option value={current.stored_session_id}>{current.stored_session_id}</option>}
        {inspection.sessions?.map(s=><option key={s.id} value={s.id}>{s.title} · {s.id}</option>)}
      </select></label>
      <label>{t('source.executor.account')}<select value={accountId} disabled={busy} onChange={e=>{setAccountId(e.target.value);setReconciled(false);setReceipts([]);}}>
        <option value="">{t('source.executor.nativeAccountUnspecified')}</option>
        {inspection.accounts?.map(a=><option key={a.id} value={a.id}>{a.connector} / {a.alias} · {a.status}</option>)}
      </select></label>
      {inspection.toolsets?.map(row=><p key={row.name}>{row.name}: {row.enabled?'✓':'—'} {row.tools.join(', ')}</p>)}
      <label>{t('source.executor.nativeSettings')}<select value={setupMethod} onChange={e=>setSetupMethod(e.target.value)} disabled={busy}>
        <option value="mcp">MCP / {t('source.executor.managed')}</option><option value="browser_controller">{t('source.executor.browser')}</option>
        {inspection.toolsets?.map(row=><option key={row.name} value={'toolset:'+row.name}>{row.name}</option>)}
      </select></label>
      <div className="sourceUpdateActions">
        <button type="button" className="secondaryButton" disabled={!route||busy||demo} onClick={()=>void run('configure')}>{t('source.executor.configureOfficial')}</button>
        <button type="button" className="secondaryButton" disabled={!route||!storedId||busy||demo||Boolean(accountId&&!account)} onClick={()=>route&&onBind({connection_id:route.connectionId,profile:route.profile,target_profile:route.targetProfile,method:'native_session',stored_session_id:storedId,...(account?{provider_id:account.connector,account_id:account.id,account_alias:account.alias}:{})})}>{t('source.executor.bind')}</button>
        <button type="button" className="secondaryButton" disabled={!bound||busy||demo||unknown||!reconciled} onClick={()=>void run('read_test')}>{t('source.executor.testRead')}</button>
        <button type="button" className="secondaryButton" disabled={!bound||busy||demo} onClick={()=>void run('read_receipts')}>{t('source.executor.receipts')}</button>
        <button type="button" className="secondaryButton" disabled={!current||!route||busy||demo} onClick={()=>void run('open_native')}>{t('source.executor.openNative')}</button>
      </div>
      {!bound&&<p>{t('source.executor.saveFirst')}</p>}{bound&&!reconciled&&<p>{t('source.executor.reconcileFirst')}</p>}
      <p>{t('source.executor.nativeBoundary')}</p>
    </>}
    {activity&&<p>{t("source.executor.nativeActivity")}</p>}
    {error&&<p role="alert">{t(`source.executor.error.${error}`)}</p>}
    {visible.map((r,i)=><article key={i}><strong>{t(`source.executor.receipt.${r.status}`)}</strong>
      <p>{r.checked_at} · {r.execution?.stored_session_id}</p>
      <p>{r.tool_refs?.map(tool=>`${tool.name} · ${tool.id}${tool.outcome === "reported_failure" ? " · " + t("source.executor.toolFailure") : ""}`).join(', ')}</p>
      <p>{t('source.executor.nativeBoundary')}</p>
    </article>)}
  </section>;
}
