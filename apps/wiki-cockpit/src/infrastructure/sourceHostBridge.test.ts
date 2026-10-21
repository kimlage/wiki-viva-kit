// @vitest-environment jsdom
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import type {SourceEntity} from '../types';
import {SourceHostBridge} from './sourceHostBridge';
const parent={postMessage:vi.fn()};
const originalParent=window.parent;
const protocol='wiki.source_access.v1',channel='fixture-channel-0001';
const source={source_id:'source-a',access:{binding_sha256:'a'.repeat(64)}} as SourceEntity;
function message(origin:string,data:unknown,from:unknown=parent){window.dispatchEvent(new MessageEvent('message',{origin,source:from as Window,data}));}
async function settle(){for(let i=0;i<12;i++)await Promise.resolve();}
class Port {onmessage:((event:MessageEvent)=>void)|null=null;postMessage=vi.fn();close=vi.fn();start=vi.fn();}
class Pair {static latest:Pair;port1=new Port();port2=new Port();constructor(){Pair.latest=this;}}
beforeEach(()=>{Object.defineProperty(window,'parent',{configurable:true,value:parent});parent.postMessage.mockReset();window.sessionStorage.clear();});
afterEach(()=>{Object.defineProperty(window,'parent',{configurable:true,value:originalParent});vi.unstubAllGlobals();vi.useRealTimers();});
it('HTTP pairing ignores foreign frame, raw null origin and unallowlisted hosts',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({source_host_origins:['https://hermes.example.test']})})));
 const bridge=new SourceHostBridge();let connected=false;const ready=bridge.connect().then(()=>{connected=true;});await settle();
 const hello={protocol,kind:'hello',channel};message('null',hello);message('https://foreign.test',hello);message('https://hermes.example.test',hello,{});await settle();expect(connected).toBe(false);
 message('https://hermes.example.test',hello);await ready;expect(connected).toBe(true);
 const pending=bridge.request(source,'routes');const request=parent.postMessage.mock.lastCall![0];
 message('https://hermes.example.test',{protocol,kind:'response',channel,request_id:request.request_id,ok:true,result:{routes:[]}});expect(await pending).toEqual({routes:[]});bridge.close();
 expect(parent.postMessage.mock.calls.every(c=>c[1]==='https://hermes.example.test')).toBe(true);
});
it('opaque Electron transport requires own-server attestation before any source request',async()=>{
 let attested=false;vi.stubGlobal('MessageChannel',Pair);vi.stubGlobal('fetch',vi.fn(async(path:string)=>({ok:true,json:async()=>path.includes('config')?{source_host_transport:'electron_message_port'}:path.includes('challenge')&&!path.includes('status')?{challenge:'c'.repeat(48)}:{attested}})));
 const bridge=new SourceHostBridge();let connected=false;const ready=bridge.connect().then(()=>{connected=true;});await settle();
 expect(parent.postMessage).toHaveBeenCalledWith({protocol,kind:'ready',challenge:'c'.repeat(48)},'*',[Pair.latest.port2]);
 const hello={protocol,kind:'hello',channel};Pair.latest.port1.onmessage!({data:hello} as MessageEvent);await settle();expect(connected).toBe(false);expect(Pair.latest.port1.postMessage).not.toHaveBeenCalled();
 attested=true;Pair.latest.port1.onmessage!({data:hello} as MessageEvent);await ready;
 const request=bridge.request(source,'routes');expect(Pair.latest.port1.postMessage).toHaveBeenCalled();const outgoing=Pair.latest.port1.postMessage.mock.lastCall![0];
 Pair.latest.port1.onmessage!({data:{protocol,kind:'response',channel,request_id:outgoing.request_id,ok:true,result:{routes:[]}}} as MessageEvent);await expect(request).resolves.toEqual({routes:[]});bridge.close();expect(Pair.latest.port1.close).toHaveBeenCalled();
});
it('closing during discovery prevents a stale ready message from pairing',async()=>{
 let resolve!:(v:unknown)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>{resolve=r;})));
 const bridge=new SourceHostBridge();const ready=bridge.connect();bridge.close();resolve({ok:true,json:async()=>({source_host_origins:['https://hermes.example.test']})});await expect(ready).rejects.toThrow('source_host_not_allowed');expect(parent.postMessage).not.toHaveBeenCalled();
});
it('standalone wiki never opens an ambient native connection',async()=>{
 Object.defineProperty(window,'parent',{configurable:true,value:window});const bridge=new SourceHostBridge();await expect(bridge.connect()).rejects.toThrow('source_host_standalone');expect(parent.postMessage).not.toHaveBeenCalled();
});


it('an unknown read survives bridge reopen; empty receipts do not authorize a duplicate request',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({source_host_origins:['https://hermes.example.test']})})));
 const first=new SourceHostBridge();const ready=first.connect();await settle();message('https://hermes.example.test',{protocol,kind:'hello',channel});await ready;
 const unknown=first.request(source,'read_test','fixture-route','b'.repeat(64));const original=parent.postMessage.mock.lastCall![0];const rejected=expect(unknown).rejects.toThrow('source_host_closed');first.close();await rejected;
 const reopened=new SourceHostBridge();const readyAgain=reopened.connect();await settle();message('https://hermes.example.test',{protocol,kind:'hello',channel});await readyAgain;
 const reconcile=reopened.request(source,'read_receipts','fixture-route','b'.repeat(64));const query=parent.postMessage.mock.lastCall![0];
 message('https://hermes.example.test',{protocol,kind:'response',channel,request_id:query.request_id,ok:true,result:{receipts:[]}});
 expect((await reconcile).unresolved_request).toBe(original.request_id);
 const before=parent.postMessage.mock.calls.length;await expect(reopened.request(source,'read_test','fixture-route','b'.repeat(64))).rejects.toThrow('source_read_result_unknown');expect(parent.postMessage.mock.calls.length).toBe(before);
 const finished=reopened.request(source,'read_receipts','fixture-route','b'.repeat(64));const finalQuery=parent.postMessage.mock.lastCall![0];
 message('https://hermes.example.test',{protocol,kind:'response',channel,request_id:finalQuery.request_id,ok:true,result:{receipts:[{request_id:original.request_id,status:'native_trace_observed'}]}});
 await finished;expect(window.sessionStorage.length).toBe(0);reopened.close();
});

it('native activity matches the exact source/config/route and never becomes access proof',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({source_host_origins:['https://hermes.example.test']})})));
 const bridge=new SourceHostBridge();const ready=bridge.connect();await settle();message('https://hermes.example.test',{protocol,kind:'hello',channel});await ready;
 const listener=vi.fn();bridge.subscribeActivity(listener);
 const query=bridge.request(source,'read_receipts','fixture-route','b'.repeat(64));const outgoing=parent.postMessage.mock.lastCall![0];
 message('https://hermes.example.test',{protocol,kind:'response',channel,request_id:outgoing.request_id,ok:true,result:{receipts:[]}});await query;
 const event={protocol,kind:'native_activity',channel,source:{source_id:source.source_id,binding_sha256:source.access!.binding_sha256,config_sha256:'b'.repeat(64)},route_key:'fixture-route'};
 message('https://hermes.example.test',{...event,route_key:'other-owner'});expect(listener).not.toHaveBeenCalled();
 message('https://hermes.example.test',event);expect(listener).toHaveBeenCalledTimes(1);bridge.close();
});
