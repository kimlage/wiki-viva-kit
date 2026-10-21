import React from 'react';
import {ROUTES_AREA, SIDEBAR_NAV_AREA, host, ConnectorsTab, ToolsetConfigPanel} from '@hermes/plugin-sdk';

/** Native session glue only: no tool dispatcher, model loop or provider reader. */
function createNativeSessionAccess({host, native, live, activity=()=>{}}) {
  const leases = new Map();
  const retaining = new Map();
  let closed = false;
  const watched=new Map();
  const outcome = payload => {
    let result=payload?.result;
    if(typeof result==='string'){try{result=JSON.parse(result);}catch{return 'unknown';}}
    if(result && typeof result==='object' && (result.success===false || result.isError===true || Boolean(result.error)))return 'reported_failure';
    return 'unknown'; // A generic completion cannot certify provider/resource success.
  };
  const validId = value => typeof value === 'string' && /^[\w:.-]{1,200}$/.test(value);
  const request = (route, method, params) => host.requestProfile(route, method, params, 30000, {spawnPriority:'foreground'});
  const publicRow = row => {
    const {prompt, request_sha256, ...result} = row;
    return {...result, status:result.status === 'submitted' ? 'pending' : result.status,
      identity:{status:'unknown'}, read_verified:false, write_verified:false, grants_verified:false};
  };
  const assertOpen = () => { if (closed) throw new Error('source_host_closed'); };
  async function retain(route) {
    assertOpen();
    const key = JSON.stringify([route.connectionId, route.profile, route.targetProfile]);
    if (!leases.has(key) && !retaining.has(key)) {
      const pending=(async()=>{
      if (closed || typeof host.retainProfile !== 'function' || typeof host.onEvent !== 'function') throw new Error('executor_unavailable');
      const release = await host.retainProfile(route, {spawnPriority:'foreground'});
      if (closed) { release(); throw new Error('source_host_closed'); }
      const state = {release, sessions:new Set(), events:new Map(), journal:new Map(), off:null};
      state.off = host.onEvent('*', event => {
        if (closed) return;
        // Never accept ambient events from another connection/profile. Live events
        // are hints only; terminal tracking always rechecks native history below.
        if (event.connectionId !== route.connectionId || event.profile !== route.profile || !state.sessions.has(event.session_id)) return;
        if (!Number.isSafeInteger(event.seq) || event.seq < 1) return;
        state.events.set(event.session_id, Math.max(state.events.get(event.session_id) || 0, event.seq));
        const entry={session_id:event.session_id,type:event.type,seq:event.seq};
        if(event.type==='tool.complete')entry.payload={tool_id:event.payload?.tool_id,name:event.payload?.name,outcome:event.payload?.outcome || outcome(event.payload)};
        if(event.type==='message.complete')entry.payload={persisted_turn:event.payload?.persisted_turn};
        const journal=state.journal.get(event.session_id) || [];journal.push(entry);if(journal.length>2048)journal.shift();state.journal.set(event.session_id,journal);
        for(const watch of watched.values())if(watch.row.runtime_session_id===event.session_id){
          if(['tool.start','tool.complete','message.complete','request','connection.request'].includes(event.type))activity(route,watch.ref);
          if(event.type==='message.complete' && !watch.busy){
            watch.busy=true;
            void reconcile(route,watch.ref,watch.row,watch.token).then(result=>{
              if(['native_trace_observed','native_trace_failed'].includes(result.status)){watched.delete(watch.row.request_id);activity(route,watch.ref);}
            }).catch(()=>{}).finally(()=>{watch.busy=false;});
          }
        }
        if (state.events.size > 128) state.events.delete(state.events.keys().next().value);
      });
      leases.set(key, state);
      })();
      retaining.set(key,pending);
    }
    try {await retaining.get(key);} finally {retaining.delete(key);}
    return leases.get(key);
  }
  async function resume(route, execution) {
    const lease=await retain(route); assertOpen();
    const value = await request(route, 'session.resume', {session_id:execution.stored_session_id, omit_messages:true, inline_images:false});
    assertOpen();
    if (!validId(value?.session_id) || ![value.stored_session_id, value.resumed, value.session_key].includes(execution.stored_session_id)) throw new Error('native_session_mismatch');
    lease.sessions.add(value.session_id);
    return value;
  }
  const track = (route, ref, row, tracking) => native(route, 'source-intent-track', 'POST', {...ref, request_id:row.request_id, tracking});
  async function reconcile(route, ref, row, token) {
    live(token); assertOpen();
    const session = await resume(route, row.execution); live(token);
    const replaySession=row.runtime_session_id || session.session_id;
    const replay = await request(route, 'session.events.since', {session_id:replaySession, last_seen:row.submit_after_seq || 0}); live(token);
    if (!validId(replay.epoch) || !Number.isSafeInteger(replay.latest_seq)) throw new Error('native_trace_unavailable');
    // History is the authority for intent ownership; epoch changes/truncation
    // must never attach the new replay tail to an old source operation.
    const history = await request(route, 'session.history', {session_id:session.session_id}); live(token);
    const messages = Array.isArray(history.messages) ? history.messages : [];
    const anchors = messages.map((m,i)=>({m,i})).filter(({m})=>m.role === 'user' &&
      (m.text ?? m.content) === row.prompt && (row.user_row_id === undefined || m.row_id === row.user_row_id));
    const tracking = {runtime_session_id:replaySession, epoch:replay.epoch, last_seen:replay.latest_seq, status:row.status === 'not_submitted' ? 'not_submitted' : 'submitted'};
    if (anchors.length === 1) {
      const {m,i} = anchors[0];
      if (Number.isSafeInteger(m.row_id) && m.row_id > 0) tracking.user_row_id = m.row_id;
      const next = messages.findIndex((m,j)=>j>i && m.role === 'user');
      const turn = messages.slice(i+1,next<0 ? messages.length : next);
      const historyRefs=turn.filter(m=>m.role==='tool' && validId(m.tool_call_id) && validId(m.name))
        .map(m=>({id:m.tool_call_id,name:m.name})).slice(0,64);
      let segment=[],started=false,owned=[];
      const lease=leases.get(JSON.stringify([route.connectionId,route.profile,route.targetProfile]));
      const journal=lease?.journal.get(replaySession) || [];
      const events=[...new Map([...(replay.events || []),...journal].map(event=>[event.seq,event])).values()].sort((a,b)=>a.seq-b.seq);
      if (row.epoch===replay.epoch && (!replay.truncated || journal.some(event=>event.type==='message.start'))) {
        for (const event of events) {
          if(event.session_id!==replaySession || !Number.isSafeInteger(event.seq))continue;
          if(event.type==='message.start'){segment=[];started=true;}
          if(started && event.type==='tool.complete' && validId(event.payload?.tool_id) && validId(event.payload?.name))segment.push({id:event.payload.tool_id,name:event.payload.name,outcome:event.payload?.outcome || outcome(event.payload)});
          const persisted=event.payload?.persisted_turn;
          if(started && event.type==='message.complete' && persisted?.complete===true && persisted.user_row_id===m.row_id){owned=segment;break;}
        }
      }
      const refs=historyRefs.map(ref=>owned.find(event=>event.id===ref.id && event.name===ref.name)).filter(Boolean);
      const completed = !session.running && !session.hydrating && refs.length>0;
      if (completed) {tracking.status=refs.some(ref=>ref.outcome==='reported_failure')?'native_trace_failed':'native_trace_observed';tracking.tool_refs=refs;}
    }
    const result = await track(route, ref, row, tracking); live(token);
    return publicRow(result);
  }
  return {
    async inspect(route,execution) {
      const session=await resume(route,execution);
      const result=await request(route,'tools.list',{session_id:session.session_id});
      return (result.toolsets || []).map(row=>({name:row.name,enabled:row.enabled,tools:row.tools || []}));
    },
    async read(route, ref, requestId, token) {
      // Exclusive durable claim happens BEFORE any native prompt submission.
      live(token); assertOpen();
      const claim = await native(route, 'source-intent-claim', 'POST', {...ref,request_id:requestId});
      const row = claim.intent;
      if (!claim.created) {
        live(token); assertOpen();
        return ['native_trace_observed','native_trace_failed','not_submitted'].includes(row.status)?publicRow(row):reconcile(route,ref,row,token);
      }
      let submitted = false;
      try {
        live(token); assertOpen();
        const session = await resume(route,row.execution); live(token);
        if (session.running || session.hydrating || session.pending_approval || session.open_requests?.length) throw new Error('native_session_busy');
        const replay = await request(route,'session.events.since',{session_id:session.session_id,last_seen:0}); live(token);
        if (!validId(replay.epoch) || !Number.isSafeInteger(replay.latest_seq)) throw new Error('native_trace_unavailable');
        Object.assign(row,{runtime_session_id:session.session_id,epoch:replay.epoch,last_seen:replay.latest_seq,submit_after_seq:replay.latest_seq});
        await track(route,ref,row,{runtime_session_id:session.session_id,epoch:replay.epoch,last_seen:replay.latest_seq,submit_after_seq:replay.latest_seq,status:'pending'}); live(token);
        // Recheck the canonical owner/config after all preflight awaits. Tracking
        // deliberately accepts old receipts for recovery; it is not dispatch authority.
        const binding=await native(route,'source-binding/'+encodeURIComponent(ref.source_id)+'?binding_sha256='+ref.binding_sha256); live(token); assertOpen();
        if(binding.source_id!==ref.source_id || binding.binding_sha256!==ref.binding_sha256)throw new Error('source_binding_changed');
        if(binding.config_sha256!==ref.config_sha256)throw new Error('source_configuration_changed');
        watched.set(row.request_id,{ref,row,token,busy:false});
        submitted = true; // From this boundary a timeout is UNKNOWN, never a retry.
        const ack = await request(route,'prompt.submit',{session_id:session.session_id,text:row.prompt,queued:true});
        live(token);
        const tracking={runtime_session_id:session.session_id,status:'submitted'};
        if (Number.isSafeInteger(ack?.user_row_id) && ack.user_row_id > 0) {tracking.user_row_id=ack.user_row_id;row.user_row_id=ack.user_row_id;}
        const result=await track(route,ref,row,tracking);live(token);
        return publicRow(result);
      } catch (error) {
        if (!submitted) await track(route,ref,row,{status:'not_submitted'}).catch(()=>{});
        if (submitted) throw new Error('source_read_result_unknown');
        throw error;
      }
    },
    async receipts(route,ref,token) {
      const result=await native(route,'source-read-receipts','POST',ref);live(token);
      const rows=[];
      for (const row of result.receipts || []) {
        if (['not_submitted','native_trace_observed','native_trace_failed'].includes(row.status)) rows.push(publicRow(row));
        else {
          if(row.execution.connection_id!==route.connectionId || row.execution.profile!==route.profile || row.execution.target_profile!==route.targetProfile)throw new Error('executor_profile_mismatch');
          rows.push(await reconcile(route,{source_id:row.source_id,binding_sha256:row.binding_sha256,config_sha256:row.config_sha256},row,token));
        }
      }
      return {receipts:rows,...(rows.find(row=>['pending','submitted'].includes(row.status))?{unresolved_request:rows.find(row=>['pending','submitted'].includes(row.status)).request_id}:{})};
    },
    async open(route,execution) {
      if (typeof host.openSession !== 'function') throw new Error('executor_unavailable');
      await host.openSession(execution.stored_session_id,{route,awaitHydration:true,forceResume:true});
      return {status:'native_session_opened'};
    },
    dispose() {closed=true;watched.clear();for(const state of leases.values()){state.off();state.release();}leases.clear();}
  };
}

/** Credential-free, source-bound iframe adapter. Never expose generic RPC/REST. */
function createSourceBridge({host, api, openSetup, frameWindow, wikiOrigin, channel, generation, currentGeneration, reply}) {
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
  const newSessionAccess = () => createNativeSessionAccess({host,native,live,activity:(route,source)=>{if(alive && currentGeneration()===generation)reply({protocol:'wiki.source_access.v1',kind:'native_activity',channel,source,route_key:key(route)});}});
  let sessions = newSessionAccess();
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
      if (m.kind === 'close' && m.channel === channel) { session++; requests.clear(); sessions.dispose(); sessions=newSessionAccess(); return true; }
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


// Installer replaces only this loopback URL; no source/account data is bundled.
const boardURL = 'http://127.0.0.1:8765/board';
function WikiSurface({sources=false}) {
  const [generation,setGeneration]=React.useState(0);
  const [setup,setSetup]=React.useState(null);
  const frame=React.useRef(null);
  const epoch=React.useRef(generation);epoch.current=generation;
  const bridge=React.useRef(null);
  const url=new URL(sources?'/w?dock=source':boardURL,boardURL).href;
  React.useEffect(()=>{
    const origin=new URL(boardURL).origin;
    const channel=crypto.randomUUID();
    let outputPort=null;
    let handshakes=0;
    const current=createSourceBridge({host,api:request=>{
      if (!window.hermesDesktop?.api) throw new Error('executor_unavailable');
      return window.hermesDesktop.api(request);
    },openSetup:async value=>{
      if (value.method === 'browser_controller' ? !ToolsetConfigPanel : !ConnectorsTab) throw new Error('executor_unavailable');
      setSetup(value);
    },frameWindow:()=>frame.current?.contentWindow,wikiOrigin:origin,channel,generation,
      currentGeneration:()=>epoch.current,reply:value=>{ if (outputPort) outputPort.postMessage(value); else frame.current?.contentWindow?.postMessage(value,origin); }});
    bridge.current=current;
    const receive=event=>{
      const m=event.data;
      if (event.origin===origin && event.source===frame.current?.contentWindow && m?.protocol==='wiki.source_access.v1' && m.kind==='ready' && event.ports.length===1) {
        const port=event.ports[0];const attempt=++handshakes;
        if (!/^[a-f0-9]{48}$/.test(m.challenge || '')) {port.close();return;}
        // Opaque file:// parent: pair through the authenticated native backend.
        // Only a challenge and port cross the frame boundary, never credentials.
        const desktop=window.hermesDesktop;
        if (!desktop?.api) {port.close();return;}
        void desktop.api({path:'/api/plugins/wiki-viva-board/bridge-attest',method:'POST',body:{challenge:m.challenge},timeoutMs:20000})
          .then(result=>{
            if (result?.attested!==true || epoch.current!==generation || attempt!==handshakes) {port.close();return;}
            outputPort?.close();outputPort=port;
            port.onmessage=message=>{if(outputPort===port)void current.receivePort(message.data);};port.start();current.hello();
          }).catch(()=>port.close());
        return;
      }
      void current.receive(event);
    };
    window.addEventListener('message',receive);
    current.hello();
    return ()=>{handshakes++;outputPort?.close();current.dispose();window.removeEventListener('message',receive);bridge.current=null;};
  },[generation,sources]);
  return React.createElement('section',{style:{height:'100%',minHeight:'80vh',display:'flex',flexDirection:'column'}},
    React.createElement('header',{style:{display:'flex',gap:16,padding:'8px 16px',alignItems:'center'}},
      React.createElement('strong',null,sources?'Wiki Viva · Fontes e acessos':'Wiki Viva · Kanban'),
      React.createElement('a',{href:url,target:'_blank',rel:'noopener noreferrer'},'Open wiki'),
      React.createElement('button',{onClick:()=>{setSetup(null);setGeneration(n=>n+1);}},'Reload')),
    setup && React.createElement('section',{role:'dialog','aria-label':'Configurar executor da fonte',style:{border:'1px solid currentColor',padding:16,overflow:'auto',maxHeight:'75vh'}},
      React.createElement('header',null,
        React.createElement('strong',null,setup.binding.source_id+' · '+setup.route.connectionId+' / '+setup.route.profile),
        React.createElement('p',null,'Configuração oficial do Hermes. Depois volte à fonte para pedir uma leitura à conversa nativa; configurar não comprova acesso.'),
        React.createElement('button',{onClick:()=>setSetup(null)},'Voltar à fonte')),
      setup.method === 'browser_controller'
        ? React.createElement(ToolsetConfigPanel,{toolset:'browser',profile:{connectionId:setup.route.connectionId,profile:setup.route.profile}})
        : React.createElement(ConnectorsTab,{gateway:null,profile:{connectionId:setup.route.connectionId,profile:setup.route.profile}})),
    React.createElement('iframe',{ref:frame,key:generation,src:url,title:sources?'Wiki Viva sources and access':'Wiki Viva action board',
      onLoad:()=>bridge.current?.hello(),style:{border:0,width:'100%',flex:1,minHeight:'75vh'},referrerPolicy:'no-referrer',
      sandbox:'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox'}));
}
export default {id:'wiki-viva-board',name:'Wiki Viva Kanban',defaultEnabled:true,register(ctx){ctx.registerMany([
  {id:'page',area:ROUTES_AREA,data:{path:'/wiki-board'},render:()=>React.createElement(WikiSurface)},
  {id:'sources',area:ROUTES_AREA,data:{path:'/wiki-sources'},render:()=>React.createElement(WikiSurface,{sources:true})},
  {id:'nav',area:SIDEBAR_NAV_AREA,data:{path:'/wiki-board',label:'Wiki Kanban',codicon:'project'}},
  {id:'sources-nav',area:SIDEBAR_NAV_AREA,data:{path:'/wiki-sources',label:'Fontes e acessos',codicon:'plug'}}
]);}};
