import React from 'react';
import {ROUTES_AREA, SIDEBAR_NAV_AREA, host, ConnectorsTab, ToolsetConfigPanel} from '@hermes/plugin-sdk';

/** Credential-free, source-bound iframe adapter. Never expose generic RPC/REST. */
function createSourceBridge({host, api, openSetup, frameWindow, wikiOrigin, channel, generation, currentGeneration, reply}) {
  const actions = new Set(['routes', 'inspect', 'configure', 'read_test', 'read_receipts']);
  const requests = new Map();
  let alive = true;
  let session = 0;
  const live = token => { if (!alive || currentGeneration() !== generation || token !== session) throw new Error("source_binding_changed"); };
  const safe = value => typeof value === 'string' && value.length > 0 && value.length <= 240 && !/[\u0000-\u001f]|:\/\/|[?&#=]|\bbearer\s/i.test(value);
  const key = route => JSON.stringify([route.connectionId, route.profile, route.targetProfile]);
  const failure = error => {
    const text = String(error?.data?.reason || error?.reason || error?.message || '');
    for (const code of ['source_binding_changed', 'source_configuration_changed', 'executor_profile_mismatch', 'source_policy_denied', 'source_request_reused', 'source_read_result_unknown', 'source_read_adapter_not_implemented', 'source_access_repository_locator_mismatch', 'source_access_resource_not_supported', 'source_configuration_unavailable']) if (text.includes(code)) return code;
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
        host.requestProfile(route,'connectors.list',{owner:{type:'account'}},15000,{spawnPriority:'foreground'}),
        host.requestProfile(route,'mcp.servers.status',{},15000,{spawnPriority:'foreground'})
      ]);
      const managed = results[0].status === 'fulfilled' ? results[0].value : null;
      const mcp = results[1].status === 'fulfilled' ? results[1].value : null;
      live(token);
      let accounts = [], account_error = null;
      if (managed?.available === true) {
        try {
          const rows = await host.requestProfile(route,'connectors.accounts',{},15000,{spawnPriority:'foreground'});
          live(token);
          accounts = (Array.isArray(rows?.accounts) ? rows.accounts : []).filter(r=>!r.disabled && safe(r.connection_id) && safe(r.connector) && /^[a-z0-9][a-z0-9-]{0,31}$/.test(r.alias || ''))
            .map(r=>({id:r.connection_id,connector:r.connector,alias:r.alias,label:safe(r.label)?r.label:r.alias,status:['active','expired','revoked','pending','failed','inactive'].includes(r.status)?r.status:'unknown'}));
        } catch (error) { account_error = failure(error); }
      }
      const providers = [
        ...(managed?.available && Array.isArray(managed.connectors) ? managed.connectors.filter(r=>safe(r.connector)).map(r=>({id:r.connector,label:r.connector,method:'managed_connector'})) : []),
        ...(Array.isArray(mcp?.servers) ? mcp.servers.filter(r=>safe(r.name)).map(r=>({id:r.name,label:r.name,method:'mcp'})) : [])
      ];
      return {binding,route,providers,accounts,managed_available:managed?.available === true,
        mcp_available:Boolean(mcp), support_errors:[...results.map(r=>r.status==='rejected'?failure(r.reason):null),account_error],
        connection_verified:false,read_verified:false};
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
    if (message.action === 'read_receipts') return native(route,'source-read-receipts','POST',body);
    try { return await native(route,'source-read-test','POST',{...body,request_id:message.request_id}); }
    catch(error) { if (['source_binding_changed','source_configuration_changed','executor_profile_mismatch','source_request_reused','source_read_adapter_not_implemented'].includes(failure(error))) throw error; throw new Error('source_read_result_unknown'); }
  };
  const receiveBound = async m => {
      if (!alive || currentGeneration() !== generation || !m || m.protocol !== 'wiki.source_access.v1') return false;
      if (m.kind === 'close' && m.channel === channel) { session++; requests.clear(); return true; }
      const token = session;
      if (m.kind !== 'request' || m.channel !== channel || !actions.has(m.action) || !/^[a-zA-Z0-9-]{16,80}$/.test(m.request_id || '') ||
          !/^[\w-]{1,160}$/.test(m.source?.source_id || '') || !/^[a-f0-9]{64}$/.test(m.source?.binding_sha256 || '') ||
          Object.keys(m).some(k=>!['protocol','kind','channel','action','request_id','source','route_key','setup_method'].includes(k)) ||
          Object.keys(m.source).some(k=>!['source_id','binding_sha256','config_sha256'].includes(k))) return false;
      if (m.setup_method !== undefined && (m.action !== 'configure' || !['local_git','mcp','managed_connector','browser_controller'].includes(m.setup_method))) return false;
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
    dispose() { alive=false;requests.clear(); },
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
        React.createElement('p',null,'Configuração oficial do Hermes. Configurar um conector não verifica a conta da fonte; volte e teste a leitura.'),
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
