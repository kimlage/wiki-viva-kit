import React from 'react';
import {ROUTES_AREA, SIDEBAR_NAV_AREA, host, ConnectorsTab, ToolsetConfigPanel} from '@hermes/plugin-sdk';

/* INLINE_SOURCE_BRIDGE */

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
      if (['browser_controller','native_toolset'].includes(value.method) ? !ToolsetConfigPanel : !ConnectorsTab) throw new Error('executor_unavailable');
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
      ['browser_controller','native_toolset'].includes(setup.method)
        ? React.createElement(ToolsetConfigPanel,{toolset:setup.toolset || 'browser',profile:{connectionId:setup.route.connectionId,profile:setup.route.profile}})
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
