import {createNativeSessionAccess} from './native-session.mjs';
/** Credential-free, source-bound iframe adapter. Never expose generic RPC/REST. */
export function createSourceBridge({host, api, openSetup, frameWindow, wikiOrigin, channel, generation, currentGeneration, reply}) {
  const actions = new Set(['routes', 'inspect', 'configure', 'read_test', 'read_receipts', 'open_native']);
  const requests = new Map();
  let alive = true;
  let session = 0;
  const live = token => { if (!alive || currentGeneration() !== generation || token !== session) throw new Error("source_binding_changed"); };
  const safe = value => typeof value === 'string' && value.length > 0 && value.length <= 240 && !/[\u0000-\u001f]|:\/\/|[?&#=]|\bbearer\s/i.test(value);
  const key = route => JSON.stringify([route.connectionId, route.profile, route.targetProfile]);
  const failure = error => {
    const text = String(error?.data?.reason || error?.reason || error?.message || '');
    for (const code of ['source_binding_changed', 'source_configuration_changed', 'executor_profile_mismatch', 'source_policy_denied', 'source_request_reused', 'source_read_result_unknown', 'source_read_adapter_not_implemented', 'native_session_required', 'native_session_mismatch', 'native_session_busy', 'native_trace_unavailable', 'source_access_repository_locator_mismatch', 'source_access_resource_not_supported', 'source_configuration_unavailable']) if (text.includes(code)) return code;
    if (/404|not_found/i.test(text)) return 'source_read_adapter_not_implemented';
    if (/org_access_denied|forbidden_scope|4030/.test(text)) return 'authority_blocked';
    if (/needs_nous_auth|401|4032/.test(text)) return 'authorization_missing';
    return 'executor_unavailable';
  };
  const routes = async () => {
    if (typeof host.profileRoutes !== 'function' || typeof host.requestProfile !== 'function') throw new Error('executor_unavailable');
    const rows = await host.profileRoutes();
    return (Array.isArray(rows) ? rows : []).filter(r => ['connectionId', 'profile', 'targetProfile'].every(k => safe(r[k])) && ['local','remote'].includes(r.mode))
      .map(r => ({connectionId:r.connectionId,profile:r.profile,targetProfile:r.targetProfile,mode:r.mode,key:key(r)}));
  };
  const native = async (route, suffix, method='GET', body) => api({
    path: '/api/plugins/wiki-viva-board/' + suffix + (suffix.includes('?') ? '&' : '?') + 'profile=' + encodeURIComponent(route.targetProfile),
    method, body, connectionId:route.connectionId, profile:route.profile, priority:'foreground', timeoutMs:35000
  });
  const sessions = createNativeSessionAccess({host,native,live,activity:(route,source)=>{if(alive && currentGeneration()===generation)reply({protocol:'wiki.source_access.v1',kind:'native_activity',channel,source,route_key:key(route)});}});
  const routeMatches = (execution, route) => execution && execution.connection_id === route.connectionId && execution.profile === route.profile && execution.target_profile === route.targetProfile;
  const perform = async (message, token) => {
    live(token);
    const available = await routes();
    live(token);
    if (message.action === 'routes') return {routes:available,capabilities:['inspect','configure','read_test','read_receipts']};
    const route = available.find(r => r.key === message.route_key);
    if (!route) throw new Error('executor_unavailable');
    const ref = message.source;
    const binding = await native(route, 'source-binding/' + encodeURIComponent(ref.source_id) + '?binding_sha256=' + ref.binding_sha256);
    live(token);
    if (binding.source_id !== ref.source_id || binding.binding_sha256 !== ref.binding_sha256 || !/^[a-f0-9]{64}$/.test(binding.config_sha256)) throw new Error('source_binding_changed');
    if (ref.config_sha256 && ref.config_sha256 !== binding.config_sha256) throw new Error('source_configuration_changed');
    if (message.action === 'inspect') {
      const results = await Promise.allSettled([
        host.requestProfile(route,'session.list',{limit:100,include_hidden:true},15000,{spawnPriority:'foreground'}),
        host.requestProfile(route,'connectors.list',{owner:{type:'account'}},15000,{spawnPriority:'foreground'}),
        host.requestProfile(route,'mcp.servers.status',{},15000,{spawnPriority:'foreground'})
      ]);
      live(token);
      const roster=results[0].status==='fulfilled'?results[0].value:null;
      const managed=results[1].status==='fulfilled'?results[1].value:null;
      const mcp=results[2].status==='fulfilled'?results[2].value:null;
      let accounts=[],account_error=null,toolsets=[];
      if (managed?.available===true) {
        try {
          const result=await host.requestProfile(route,'connectors.accounts',{},15000,{spawnPriority:'foreground'});live(token);
          accounts=(result.accounts || []).filter(r=>!r.disabled && safe(r.connection_id) && safe(r.connector) && /^[a-z0-9][a-z0-9-]{0,31}$/.test(r.alias || ''))
            .map(r=>({id:r.connection_id,connector:r.connector,alias:r.alias,label:safe(r.label)?r.label:r.alias,status:r.status}));
        } catch(error) {account_error=failure(error);}
      }
      const execution=binding.access_policy?.execution;
      if (routeMatches(execution,route) && execution.method==='native_session') {
        try {toolsets=await sessions.inspect(route,execution);live(token);} catch(error) {account_error=failure(error);}
      }
      return {binding,route,sessions:(roster?.sessions || []).filter(r=>safe(r.id)).map(r=>({id:r.resolved_id || r.id,title:safe(r.title)?r.title:r.id})),
        accounts,toolsets,managed_available:managed?.available===true,mcp_available:Boolean(mcp),
        providers:(managed?.connectors || []).filter(r=>safe(r.connector)).map(r=>({id:r.connector,label:r.connector,method:'native_session'})),
        support_errors:[...results.map(r=>r.status==='rejected'?failure(r.reason):null),account_error],connection_verified:false,read_verified:false};
    }
    if (message.action === 'configure') {
      // This opens the real host UI. Only direct operator interaction there
      // starts a connection or specific consent. No connect/grant RPC here.
      live(token);
      await openSetup({route,binding,method:message.setup_method || binding.access_policy?.execution?.method || 'mcp'});
      return {status:'official_setup_opened',route,source_id:ref.source_id};
    }
    live(token);
    const execution = binding.access_policy?.execution;
    if (!routeMatches(execution, route)) throw new Error('executor_profile_mismatch');
    const body = {source_id:ref.source_id,binding_sha256:ref.binding_sha256,config_sha256:binding.config_sha256};
    if (execution?.method !== 'native_session') throw new Error('native_session_required');
    if (message.action === 'open_native') return sessions.open(route,execution);
    if (message.action === 'read_receipts') return sessions.receipts(route,body,token);
    return sessions.read(route,body,message.request_id,token);
  };
  const receiveBound = async m => {
      if (!alive || currentGeneration() !== generation || !m || m.protocol !== 'wiki.source_access.v1') return false;
      if (m.kind === 'close' && m.channel === channel) { session++; requests.clear(); return true; }
      const token = session;
      if (m.kind !== 'request' || m.channel !== channel || !actions.has(m.action) || !/^[a-zA-Z0-9-]{16,80}$/.test(m.request_id || '') ||
          !/^[\w-]{1,160}$/.test(m.source?.source_id || '') || !/^[a-f0-9]{64}$/.test(m.source?.binding_sha256 || '') ||
          Object.keys(m).some(k=>!['protocol','kind','channel','action','request_id','source','route_key','setup_method'].includes(k)) ||
          Object.keys(m.source).some(k=>!['source_id','binding_sha256','config_sha256'].includes(k))) return false;
      if (m.setup_method !== undefined && (m.action !== 'configure' || !['mcp','managed_connector','browser_controller'].includes(m.setup_method))) return false;
      const fingerprint = JSON.stringify(m);
      let pending = requests.get(m.request_id);
      if (pending && pending.fingerprint !== fingerprint) return false;
      if (!pending) {
        if (requests.size >= 256) return false; // bounded per frame; explicit reload resets it.
        pending={fingerprint,token,promise:perform(m,token).then(result=>({ok:true,result}),error=>({ok:false,error_code:failure(error)}))};
        requests.set(m.request_id,pending);
      }
      const response=await pending.promise;
      if (alive && pending.token === session && currentGeneration() === generation) reply({protocol:m.protocol,kind:'response',channel,request_id:m.request_id,...response});
      return true;
  };
  return {
    hello() { reply({protocol:'wiki.source_access.v1',kind:'hello',channel,actions:[...actions]}); },
    dispose() { alive=false;requests.clear();sessions.dispose(); },
    receivePort: receiveBound,
    async receive(event) {
      if (!alive || currentGeneration() !== generation || event.origin !== wikiOrigin || event.source !== frameWindow()) return false;
      const m = event.data;
      if (!m || m.protocol !== 'wiki.source_access.v1') return false;
      if (m.kind === 'ready') { this.hello(); return true; }
      return receiveBound(m);
    }
  };
}
