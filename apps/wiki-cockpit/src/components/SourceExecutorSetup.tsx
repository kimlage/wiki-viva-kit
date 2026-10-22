import { useEffect, useRef, useState } from "react";
import { t } from "../data/i18n";
import { contextLabel } from "../data/presentation";
import type { SourceEntity, SourceExecutionBinding, SourceConnectionBinding } from "../types";
import type { SourceHostPort, ExecutorRoute, HostResult, NativeReadReceipt, HostAction } from "../application/sourceAccess";
import { savedSourceRoute, sourceConnectionState } from "../application/sourceConnection";

export function SourceExecutorSetup({ source, demo, onBind, onConnectBinding, createHost }: {source: SourceEntity; demo: boolean; createHost?: () => SourceHostPort; onBind: (execution: SourceExecutionBinding) => void; onConnectBinding?: (connection: SourceConnectionBinding) => void}) {
  const bridge = useRef<SourceHostPort>();
  const factory = useRef(createHost); factory.current = createHost;
  const generation = useRef(0), active = useRef(false);
  const [routes, setRoutes] = useState<ExecutorRoute[]>([]);
  const [routeKey, setRouteKey] = useState("");
  const [inspection, setInspection] = useState<HostResult>();
  const current = source.access_policy?.execution;
  const connection = source.access_policy?.connection;
  const owner = connection || current;
  const [storedId, setStoredId] = useState(current?.stored_session_id || "");
  const [accountId, setAccountId] = useState(owner?.account_id || "");
  const [setupMethod, setSetupMethod] = useState("mcp");
  const [receipts, setReceipts] = useState<NativeReadReceipt[]>([]);
  const [activity, setActivity] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!source.access?.valid_until) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [source.access?.valid_until]);
  const route = routes.find(row => row.key === routeKey);
  const account = inspection?.accounts?.find(row => row.id === accountId);
  const connectionBound = Boolean(owner && route && owner.connection_id === route.connectionId && owner.profile === route.profile && owner.target_profile === route.targetProfile &&
    (owner.account_id ? account?.id === owner.account_id && account.alias === owner.account_alias && account.connector === owner.provider_id : !accountId));
  const bound = connectionBound && (!current || current.stored_session_id === storedId);
  const recoveryBound = Boolean(owner && route && inspection && owner.connection_id === route.connectionId &&
    owner.profile === route.profile && owner.target_profile === route.targetProfile);

  useEffect(() => {
    const epoch = ++generation.current;
    bridge.current?.close(); bridge.current = undefined; active.current = true;
    setRoutes([]); setRouteKey(""); setInspection(undefined);
    setStoredId(current?.stored_session_id || ""); setAccountId(owner?.account_id || "");
    setReceipts([]); setError(""); setUnknown(false); setActivity(false); setBusy(!demo);
    if (!demo) void (async () => {
      try {
        if (!factory.current) throw new Error("source_host_standalone");
        const host = factory.current(); bridge.current = host;
        host.subscribeActivity?.(() => { if (epoch === generation.current) setActivity(true); });
        await host.connect(); if (epoch !== generation.current) return;
        const result = await host.request(source, "routes"); if (epoch !== generation.current) return;
        const available = result.routes || []; setRoutes(available);
        const selected = savedSourceRoute(source, available);
        if (!selected) {
          if (!available.length) throw new Error("executor_unavailable");
          if (owner) throw new Error("executor_profile_mismatch");
          return;
        }
        setRouteKey(selected.key);
        const details = await host.request(source, "inspect", selected.key);
        if (epoch === generation.current) setInspection(details);
      } catch (cause) { if (epoch === generation.current) setError(cause instanceof Error ? cause.message : "executor_unavailable"); }
      finally { if (epoch === generation.current) { active.current = false; setBusy(false); } }
    })();
    else active.current = false;
    return () => { generation.current++; bridge.current?.close(); bridge.current = undefined; };
  }, [source.source_id, source.access?.binding_sha256, demo]);

  const run = async (action: HostAction, selected = route) => {
    if (demo || active.current || !bridge.current || !selected) return;
    const epoch = generation.current, host = bridge.current;
    active.current = true; setBusy(true); setError("");
    const request = (kind: HostAction) => host.request(source, kind, selected.key,
      kind === "inspect" ? undefined : inspection?.binding?.config_sha256, kind === "configure" ? setupMethod : undefined);
    try {
      if (action === "inspect") {
        const result = await request(action);
        if (epoch === generation.current) setInspection(result);
      } else if (action === "read_test" || action === "read_receipts") {
        // One deliberate click first reconciles the existing request. An unknown
        // or pending effect never becomes permission to submit another prompt.
        const prior = await request("read_receipts"); if (epoch !== generation.current) return;
        const pending = Boolean(prior.unresolved_request) || (prior.receipts || []).some(row => ["pending", "submitted"].includes(row.status));
        setReceipts(prior.receipts || []); setUnknown(pending); setActivity(false);
        if(prior.execution_hold && !pending) {setError(prior.execution_hold);return;}
        if (action === "read_test" && !pending) {
          const result = await request("read_test"); if (epoch !== generation.current) return;
          setReceipts([result as NativeReadReceipt]); setUnknown(["pending", "submitted"].includes(result.status || ""));
        }
      } else await request(action);
    } catch (cause) {
      if (epoch === generation.current) {
        const code = cause instanceof Error ? cause.message : "executor_unavailable"; setError(code);
        if (code === "source_read_result_unknown") setUnknown(true);
      }
    } finally { if (epoch === generation.current) { active.current = false; setBusy(false); } }
  };
  const selectRoute = (key: string) => {
    const selected = routes.find(row => row.key === key); if (!selected || active.current) return;
    setRouteKey(key); setInspection(undefined); setReceipts([]); setUnknown(false);
    const saved = savedSourceRoute(source, [selected]);
    setStoredId(saved ? current?.stored_session_id || "" : ""); setAccountId(saved ? owner?.account_id || "" : "");
    void run("inspect", selected);
  };
  const routeLabel = (row: ExecutorRoute) => `${t(row.mode === "local" ? "source.connection.local" : "source.connection.remote")} · ${row.label || (row.profile === "default" ? t("source.connection.defaultProfile") : contextLabel(row.profile))}`;
  const state = sourceConnectionState(source, { loading: busy && !inspection, error: error || inspection?.binding?.execution_hold || "", available: Boolean(route && inspection), accountFound: Boolean(account), bindingMatches: bound && account?.status === "active", accountsAvailable: inspection?.accounts_available === true, unresolved: unknown, needsContext: routes.length > 1 && !route, pending: receipts.some(row => ["pending", "submitted"].includes(row.status)), queued: receipts.some(row => ["pending", "submitted"].includes(row.status) && row.native_submission_status === "queued"), now, bindingSha: inspection?.binding?.binding_sha256 });
  const same = (a: NativeReadReceipt["execution"], b: NativeReadReceipt["execution"]) => Boolean(a && b && a.method === b.method &&
    (["connection_id", "profile", "target_profile", "provider_id", "account_id", "account_alias"] as const).every(key => a[key] === b[key]) &&
    (a.method !== "native_session" || b.method !== "native_session" || a.stored_session_id === b.stored_session_id));
  const executionOwner = current || (connection && {...connection, method: "profile_bot" as const});
  const visible = receipts.filter(row => row.source_id === source.source_id && row.binding_sha256 === source.access?.binding_sha256 && row.config_sha256 === inspection?.binding?.config_sha256 && same(row.execution, executionOwner));
  const reconnect = state === "expired" || state === "revoked";
  const needsBinding = Boolean(onConnectBinding && !connectionBound && !(recoveryBound && accountId === (owner?.account_id || "")));
  const reviewConnection = () => route && onConnectBinding?.({connection_id: route.connectionId, profile: route.profile, target_profile: route.targetProfile,
    ...(account ? {provider_id: account.connector, account_id: account.id, account_alias: account.alias} : {})});

  return <section className="sourceConnectionCard" aria-label={t("source.connection.title")} aria-busy={busy}>
    <header><h4>{t("source.connection.title")}</h4><span className={`pill pill-${state === "verified" ? "good" : "muted"}`} role="status">{t(`source.connection.state.${state}`)}</span></header>
    <dl className="sourceConnectionIdentity">
      <div><dt>{t("source.connection.source")}</dt><dd>{source.title || source.source_id}</dd></div>
      <div><dt>{t("source.connection.account")}</dt><dd>{state === "verified" ? source.access?.confirmed_identity : t("source.connection.accountUnknown")}</dd></div>
      {source.access_policy?.expected_identity && <div><dt>{t("source.access.expected")}</dt><dd>{source.access_policy.expected_identity}</dd></div>}
      <div><dt>{t("source.connection.context")}</dt><dd>{contextLabel(source.context)}</dd></div>
      {route && <div><dt>{t("source.connection.environment")}</dt><dd>{routeLabel(route)}</dd></div>}
    </dl>
    <p>{t(`source.connection.detail.${state}`)}</p>
    {routes.length > 1 && !route && <fieldset className="sourceContextChoice"><legend>{t("source.connection.chooseContext")}</legend>
      {routes.map(row => <button type="button" className="secondaryButton" key={row.key} disabled={busy} onClick={() => selectRoute(row.key)}>{routeLabel(row)}</button>)}
    </fieldset>}
    {inspection && !connectionBound && Boolean(inspection.accounts?.length) && <label>{t("source.connection.chooseAccount")}<select value={accountId} disabled={busy} onChange={event => {setAccountId(event.target.value); setReceipts([]); setUnknown(false);}}>
      <option value="">{t("source.connection.accountUnspecified")}</option>
      {inspection.accounts?.map(row => <option key={row.id} value={row.id}>{row.label || row.alias} · {row.connector}</option>)}
    </select></label>}
    <div className="sourceUpdateActions">
      <button type="button" className="btn btn--run" disabled={!route || busy || demo} onClick={() => needsBinding && !(accountId && !account) ? reviewConnection() : void run("configure")}>{t(reconnect ? "source.connection.reconnect" : "source.connection.connect")}</button>
      <button type="button" className="secondaryButton" disabled={!(unknown ? recoveryBound : bound) || busy || demo || Boolean(inspection?.binding?.execution_hold && !unknown)} onClick={() => void run(unknown ? "read_receipts" : "read_test")}>{t(unknown ? "source.connection.checkProgress" : "source.connection.test")}</button>
      {recoveryBound && (!bound || inspection?.binding?.execution_hold) && !unknown && <button type="button" className="secondaryButton" disabled={busy || demo} onClick={() => void run("read_receipts")}>{t("source.connection.checkProgress")}</button>}
      <button type="button" className="secondaryButton" disabled={!route || busy || demo} onClick={() => void run("inspect")}>{t("source.connection.refresh")}</button>
      {owner && (activity || unknown || state === "busy" || state === "approval" || state === "paused") && <button type="button" className="secondaryButton" disabled={!route || busy || demo} onClick={() => void run("open_native")}>{t("source.connection.openExecution")}</button>}
    </div>
    {inspection && !connectionBound && <p className="sourceConnectionHint">{t("source.connection.saveContext")}</p>}
    {visible.map((row, index) => <p key={index} role="status">{t(`source.executor.receipt.${row.status}`)}</p>)}
    <details className="sourceConnectionAdvanced">
      <summary>{t("source.connection.advanced")}</summary>
      <p>{t("source.connection.executionBoundary")}</p>
      <label>{t("source.connection.environment")}<select value={routeKey} disabled={busy || !routes.length} onChange={event => selectRoute(event.target.value)}>
        <option value="">{t("source.connection.chooseContext")}</option>{routes.map(row => <option key={row.key} value={row.key}>{routeLabel(row)}</option>)}
      </select></label>
      {inspection && <>
        <label>{t("source.executor.nativeSession")}<select value={storedId} disabled={busy} onChange={event => { setStoredId(event.target.value); setReceipts([]); setUnknown(false); }}>
          <option value="">{t("source.executor.choose")}</option>
          {current?.stored_session_id && !inspection.sessions?.some(row => row.id === current.stored_session_id) && <option value={current.stored_session_id}>{current.stored_session_id}</option>}
          {inspection.sessions?.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}
        </select></label>
        <label>{t("source.executor.account")}<select value={accountId} disabled={busy} onChange={event => { setAccountId(event.target.value); setReceipts([]); setUnknown(false); }}>
          <option value="">{t("source.executor.nativeAccountUnspecified")}</option>
          {inspection.accounts?.map(row => <option key={row.id} value={row.id}>{row.label || row.alias} · {row.connector}</option>)}
        </select></label>
        <label>{t("source.executor.nativeSettings")}<select value={setupMethod} onChange={event => setSetupMethod(event.target.value)} disabled={busy}>
          <option value="mcp">MCP / {t("source.executor.managed")}</option><option value="browser_controller">{t("source.executor.browser")}</option>
          {inspection.toolsets?.map(row => <option key={row.name} value={"toolset:" + row.name}>{row.name}</option>)}
        </select></label>
        <div className="sourceUpdateActions">
          <button type="button" className="secondaryButton" disabled={!route || !storedId || busy || demo || Boolean(accountId && !account)} onClick={() => route && onBind({ connection_id: route.connectionId, profile: route.profile, target_profile: route.targetProfile, method: "native_session", stored_session_id: storedId, ...(account ? { provider_id: account.connector, account_id: account.id, account_alias: account.alias } : {}) })}>{t("source.executor.bind")}</button>
          {owner && <button type="button" className="secondaryButton" disabled={!route || busy || demo} onClick={() => void run("open_native")}>{t("source.connection.openExecution")}</button>}
        </div>
        {inspection.toolsets?.map(row => <p key={row.name}><code>{row.name}</code>: {row.enabled ? "✓" : "—"}</p>)}
        {inspection.support_errors?.filter((code): code is string => Boolean(code)).map((code, index) => <p key={index}>{t(`source.executor.error.${code}`)}</p>)}
        <p>{t("source.executor.saveFirst")}</p>
      </>}
      {error && <p role="alert">{t(`source.executor.error.${error}`)}</p>}
      {visible.map((row, index) => <article key={index}><p>{row.checked_at} · {row.execution?.method === "native_session" ? row.execution.stored_session_id : row.owner_stored_session_id}</p><p>{row.tool_refs?.map(tool => `${tool.name} · ${tool.id}${tool.outcome === "reported_failure" ? " · " + t("source.executor.toolFailure") : ""}`).join(", ")}</p></article>)}
    </details>
  </section>;
}
