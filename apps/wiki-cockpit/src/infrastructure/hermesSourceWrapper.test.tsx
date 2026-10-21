// @vitest-environment jsdom
import React from 'react';
import {readFileSync,existsSync} from 'node:fs';
import {resolve} from 'node:path';
const candidates=['integrations/hermes/wiki-viva-board/plugin.js','../../integrations/hermes/wiki-viva-board/plugin.js'].map(p=>resolve(process.cwd(),p));
const wrapperCode=readFileSync(candidates.find(p=>existsSync(p))!,'utf8');
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
const code=wrapperCode
 .replace(/^import React from 'react';\n/,'').replace(/^import \{[^\n]+\} from '@hermes\/plugin-sdk';\n/m,'').replace('export default {','return {');
afterEach(()=>{cleanup();delete (window as unknown as {hermesDesktop?:unknown}).hermesDesktop;});
it('reuses the same wrapper, adds source navigation, and opens actual ConnectorsTab with explicit ProfileScope',async()=>{
 const route={connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local'};
 const binding={source_id:'source-a',binding_sha256:'a'.repeat(64),config_sha256:'b'.repeat(64)};
 const api=vi.fn(async()=>binding);Object.assign(window,{hermesDesktop:{api}});
 const host={profileRoutes:vi.fn(async()=>[route]),requestProfile:vi.fn(),toolsets:{list:vi.fn(async()=>[{name:'new-native-tools',enabled:false}])}};
 const connectors=vi.fn((props:{gateway:unknown;profile:{connectionId:string;profile:string}})=><div>Official connectors {props.profile.profile}</div>);
 const browser=vi.fn((props:{toolset:string;profile:{connectionId:string;profile:string}})=><div>Official browser {props.profile.profile}</div>);
 const plugin=new Function('React','ROUTES_AREA','SIDEBAR_NAV_AREA','host','ConnectorsTab','ToolsetConfigPanel',code)(React,'routes','sidebar',host,connectors,browser);
 let contributions: {id:string;area:string;data:{path:string};render:()=>React.ReactNode}[]=[];
 plugin.register({registerMany:(rows:typeof contributions)=>{contributions=rows;}});
 expect(contributions.filter(r=>r.area==='routes').map(r=>r.data.path)).toEqual(['/wiki-board','/wiki-sources']);
 render(contributions.find(r=>r.id==='sources')!.render());
 const frame=screen.getByTitle('Wiki Viva sources and access') as HTMLIFrameElement;
 expect(frame.src).toBe('http://127.0.0.1:8765/w?dock=source');expect(api).not.toHaveBeenCalled();expect(host.requestProfile).not.toHaveBeenCalled();
 const post=vi.spyOn(frame.contentWindow!,'postMessage');fireEvent.load(frame);
 const hello=post.mock.calls[post.mock.calls.length-1][0] as {channel:string};
 window.dispatchEvent(new MessageEvent('message',{origin:'http://127.0.0.1:8765',source:frame.contentWindow,data:{protocol:'wiki.source_access.v1',kind:'request',channel:hello.channel,request_id:'fixture-request-0001',action:'configure',source:{source_id:'source-a',binding_sha256:binding.binding_sha256},route_key:JSON.stringify([route.connectionId,route.profile,route.targetProfile])}}));
 await screen.findByText('Official connectors research');
 expect(connectors.mock.calls[0][0]).toEqual({gateway:null,profile:{connectionId:'fixture',profile:'research'}});
 expect(api).toHaveBeenCalledWith(expect.objectContaining({connectionId:'fixture',profile:'research',path:expect.stringContaining('/api/plugins/wiki-viva-board/source-binding/source-a')}));
 expect(host.requestProfile).not.toHaveBeenCalled();
 fireEvent.click(screen.getByText('Voltar à fonte'));await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 window.dispatchEvent(new MessageEvent('message',{origin:'http://127.0.0.1:8765',source:frame.contentWindow,data:{protocol:'wiki.source_access.v1',kind:'request',channel:hello.channel,request_id:'fixture-request-0002',action:'configure',setup_method:'browser_controller',source:{source_id:'source-a',binding_sha256:binding.binding_sha256},route_key:JSON.stringify([route.connectionId,route.profile,route.targetProfile])}}));
 await screen.findByText('Official browser research');
 expect(browser.mock.calls[0][0]).toEqual({toolset:'browser',profile:{connectionId:'fixture',profile:'research'}});
 expect(host.requestProfile).not.toHaveBeenCalled();
 fireEvent.click(screen.getByText('Voltar à fonte'));
 window.dispatchEvent(new MessageEvent('message',{origin:'http://127.0.0.1:8765',source:frame.contentWindow,data:{protocol:'wiki.source_access.v1',kind:'request',channel:hello.channel,request_id:'fixture-request-0003',action:'configure',setup_method:'toolset:new-native-tools',source:{source_id:'source-a',binding_sha256:binding.binding_sha256},route_key:JSON.stringify([route.connectionId,route.profile,route.targetProfile])}}));
 await waitFor(()=>expect(browser.mock.calls[browser.mock.calls.length-1]?.[0]).toEqual({toolset:'new-native-tools',profile:{connectionId:'fixture',profile:'research'}}));
 expect(host.toolsets.list).toHaveBeenCalledWith({connectionId:'fixture',profile:'research'});
 expect(host.requestProfile).not.toHaveBeenCalled();
});

it('keeps the frame, bridge channel and retained native session alive while official setup takes the available space',async()=>{
 const route={connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local'};
 const execution={connection_id:'fixture',profile:'research',target_profile:'research',method:'native_session',stored_session_id:'stored-one'};
 const binding={source_id:'source-a',binding_sha256:'a'.repeat(64),config_sha256:'b'.repeat(64),access_policy:{execution}};
 const release=vi.fn(),off=vi.fn();
 const host={profileRoutes:vi.fn(async()=>[route]),retainProfile:vi.fn(async()=>release),onEvent:vi.fn(()=>off),
  requestProfile:vi.fn(async(_route:unknown,method:string)=>{
   if(method==='session.resume')return {session_id:'runtime-one',stored_session_id:'stored-one'};
   if(method==='session.list')return {sessions:[]};
   if(method==='tools.list')return {toolsets:[]};
   return {};
  }),toolsets:{list:vi.fn(async()=>[{name:'browser',enabled:true}])}};
 Object.assign(window,{hermesDesktop:{api:vi.fn(async()=>binding)}});
 const connectors=()=> <div>Official connectors</div>;
 const tools=()=> <div>Official toolset</div>;
 const plugin=new Function('React','ROUTES_AREA','SIDEBAR_NAV_AREA','host','ConnectorsTab','ToolsetConfigPanel',code)(React,'routes','sidebar',host,connectors,tools);
 let rows:{id:string;render:()=>React.ReactNode}[]=[];
 plugin.register({registerMany:(value:typeof rows)=>{rows=value;}});
 const view=render(rows.find(row=>row.id==='sources')!.render());
 const frame=screen.getByTitle('Wiki Viva sources and access') as HTMLIFrameElement;
 const frameWindow=frame.contentWindow,src=frame.src;
 const post=vi.spyOn(frameWindow!,'postMessage');fireEvent.load(frame);
 const hello=post.mock.calls[post.mock.calls.length-1][0] as {channel:string};
 let sequence=0;
 const send=(action:string,setup_method?:string)=>{
  const request_id='fixture-lifecycle-'+String(++sequence).padStart(4,'0');
  window.dispatchEvent(new MessageEvent('message',{origin:'http://127.0.0.1:8765',source:frameWindow,data:{protocol:'wiki.source_access.v1',kind:'request',channel:hello.channel,request_id,action,source:{source_id:'source-a',binding_sha256:binding.binding_sha256},route_key:JSON.stringify([route.connectionId,route.profile,route.targetProfile]),...(setup_method?{setup_method}:{})}}));
  return request_id;
 };
 const inspectId=send('inspect');
 await waitFor(()=>expect(post.mock.calls.some(([row])=>row.request_id===inspectId && row.ok===true)).toBe(true));
 expect(host.retainProfile).toHaveBeenCalledTimes(1);
 const helloCount=()=>post.mock.calls.filter(([row])=>row.kind==='hello').length;
 const count=helloCount();
 for(const [method,text] of [['mcp','Official connectors'],['browser_controller','Official toolset']]){
  send('configure',method);await screen.findByText(text);
  expect(screen.getByTitle('Wiki Viva sources and access')).toBe(frame);
  expect(frame.contentWindow).toBe(frameWindow);expect(frame.src).toBe(src);
  expect(frame.style.display).toBe('none');expect(frame.style.minHeight).toBe('0px');
  expect(screen.getByRole('dialog').style.minHeight).toBe('0px');
  expect(release).not.toHaveBeenCalled();expect(off).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Voltar à fonte'));
  await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
  expect(frame.style.display).toBe('block');expect(frame.contentWindow).toBe(frameWindow);
  expect(helloCount()).toBe(count);
 }
 expect(host.retainProfile).toHaveBeenCalledTimes(1);
 expect(host.requestProfile.mock.calls.filter(([,method])=>method==='session.resume')).toHaveLength(1);
 expect(host.requestProfile.mock.calls.some(([,method])=>method==='prompt.submit')).toBe(false);
 view.unmount();expect(release).toHaveBeenCalledTimes(1);expect(off).toHaveBeenCalledTimes(1);
});
