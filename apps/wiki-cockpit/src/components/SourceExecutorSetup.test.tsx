// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { configureLanguage } from '../data/i18n';
import type { SourceEntity, SourceExecutionBinding } from '../types';
import { SourceExecutorSetup } from './SourceExecutorSetup';
const execution: SourceExecutionBinding = { connection_id:'fixture',profile:'research',target_profile:'research',method:'native_session',stored_session_id:'stored-fixture' };
const route = {connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local',key:'fixture-route'};
const sha='a'.repeat(64),config='b'.repeat(64),request=vi.fn(),close=vi.fn();
const createHost=()=>({request,connect:async()=>{},close});
const source=(bound=true)=>({source_id:'source-a',title:'Research mail',context:'research',access:{binding_sha256:sha},access_policy:bound?{execution}:{}} as SourceEntity);
const inspection=()=>({binding:{config_sha256:config,binding_sha256:sha},sessions:[{id:'stored-fixture',title:'Existing context'}],accounts:[]});
beforeEach(()=>{configureLanguage('en');request.mockReset();close.mockReset();request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?inspection():a==='read_receipts'?{receipts:[]}:{status:'pending',source_id:'source-a',binding_sha256:sha,config_sha256:config,execution});});
afterEach(cleanup);
async function ready(){await waitFor(()=>expect((screen.getByRole('button',{name:'Connect'}) as HTMLButtonElement).disabled).toBe(false));}
function advanced(){fireEvent.click(screen.getByText('Advanced: execution and diagnostics'));}
const gatewayOrigin={schema_version:'hermes.connector_gateway_origin.v1',status:'known',profile:'research',origin:{scheme:'https',host:'fixture.example.test',port:8443},provenance:'override',resolution_scope:'process',reason_code:null,account_identity_verified:false,account_enforced:false};
it('inspects process origin separately without changing access trust or submitting a read',async()=>{
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?inspection():{route,gateway_origin:gatewayOrigin});
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();advanced();
 const before=screen.getByRole('status').textContent;
 fireEvent.click(screen.getByRole('button',{name:'Inspect gateway origin'}));
 await screen.findByText('https://fixture.example.test:8443');
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect','transport_metadata']);
 expect(request.mock.calls[request.mock.calls.length-1]?.slice(2)).toEqual(['fixture-route']);
 expect(screen.getByRole('status').textContent).toBe(before);
 expect(screen.getByText('Resolution in this Hermes process · Explicit process override')).toBeTruthy();
 expect(screen.getByText(/This does not identify an account or authorize a read/)).toBeTruthy();
});
it('discards origin from an old route even when both environments use the same profile name',async()=>{
 let resolve!: (result:unknown)=>void;
 const other={...route,connectionId:'other-device',mode:'remote',key:'other-route'};
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route,other]}:a==='inspect'?inspection():new Promise(done=>{resolve=done;}));
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();advanced();
 fireEvent.click(screen.getByRole('button',{name:'Inspect gateway origin'}));
 await screen.findByRole('button',{name:'Checking origin…'});
 fireEvent.change(screen.getByRole('combobox',{name:'Hermes environment'}),{target:{value:'other-route'}});
 await ready();await act(async()=>resolve({route,gateway_origin:gatewayOrigin}));
 expect(screen.queryByText('https://fixture.example.test:8443')).toBeNull();
 expect(screen.getByText('Connector gateway origin: Not checked')).toBeTruthy();
});
it('treats a mismatched origin response and native failure as unknown without changing access state',async()=>{
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?inspection():{route:{...route,targetProfile:'other'},gateway_origin:gatewayOrigin});
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();advanced();
 const before=screen.getByRole('status').textContent;
 fireEvent.click(screen.getByRole('button',{name:'Inspect gateway origin'}));
 await screen.findByText('Connector gateway origin: Unknown on this host');
 expect(screen.queryByText('https://fixture.example.test:8443')).toBeNull();
 expect(screen.getByRole('status').textContent).toBe(before);
 request.mockRejectedValueOnce(new Error('synthetic-only'));
 fireEvent.click(screen.getByRole('button',{name:'Inspect gateway origin'}));
 await waitFor(()=>expect((screen.getByRole('button',{name:'Inspect gateway origin'}) as HTMLButtonElement).disabled).toBe(false));
 expect(screen.queryByText('synthetic-only')).toBeNull();
 expect(screen.getByRole('status').textContent).toBe(before);
});
it.each(['removed','alias','provider','reconnected-account','discovery-unavailable','inactive'])('drops historical verified trust after current account %s and retains official recovery',async(change)=>{
 const nativeAccount={id:'account-a',connector:'fixture-mail',alias:'research',label:'Research',status:'active'};
 const boundExecution={...execution,account_id:nativeAccount.id,provider_id:nativeAccount.connector,account_alias:nativeAccount.alias};
 const observed={...source(),access_policy:{schema_version:'wiki_source_access.v1',expected_identity:'reader@example.test',coordinator:'research',executor:'Hermes',requested_scopes:['read'],execution:boundExecution},
  access:{schema_version:'wiki_source_access.v1',binding_sha256:sha,status:'verified',verified:true,expected_identity:'reader@example.test',confirmed_identity:'reader@example.test',coordinator:'research',executor:'Hermes',requested_scopes:['read'],granted_scopes:['read'],checked_at:new Date(Date.now()-1000).toISOString(),valid_until:new Date(Date.now()+60000).toISOString(),evidence_ref:'receipt:synthetic',error_code:'',execution_ready:false,business_authority:'unknown'}} as SourceEntity;
 let catalogue={...inspection(),accounts:[nativeAccount],accounts_available:true};
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?catalogue:a==='read_receipts'?{receipts:[]}:{});
 const review=vi.fn();render(<SourceExecutorSetup source={observed} demo={false} onBind={vi.fn()} onConnectBinding={review} createHost={createHost}/>);await ready();
 expect(screen.getByRole('status').textContent).toBe('Access verified');
 catalogue={...catalogue,accounts:change==='removed'?[]:[{...nativeAccount,
  ...(change==='alias'?{alias:'renamed'}:{}),...(change==='provider'?{connector:'another-provider'}:{}),
  ...(change==='reconnected-account'?{id:'replacement-account'}:{}),...(change==='inactive'?{status:'initiated'}:{})}],accounts_available:change!=='discovery-unavailable'};
 fireEvent.click(screen.getByRole('button',{name:'Refresh connection'}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('Access not verified'));
 expect(screen.queryByText('Access revoked')).toBeNull();expect(screen.queryByText('Login expired')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Connect'}));
 await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='configure')).toBe(true));
 expect(review).not.toHaveBeenCalled();
 // Receipts can be inspected on the same route even if a named account vanished.
 if(screen.queryByRole('button',{name:'Check progress'})) {
  fireEvent.click(screen.getByRole('button',{name:'Check progress'}));
  await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='read_receipts')).toBe(true));
 }
 expect(request.mock.calls.some(c=>c[1]==='read_test')).toBe(false);
});
it('keeps missing kernel admission distinct from STOP and permits official configuration',async()=>{
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?{...inspection(),binding:{...inspection().binding,execution_hold:'source_authorization_unavailable'}}:{});
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();
 expect(screen.getByRole('status').textContent).toBe('Read blocked');
 expect((screen.getByRole('button',{name:'Test access'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Connect'}));
 await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='configure')).toBe(true));
 fireEvent.click(screen.getByRole('button',{name:'Check progress'}));
 await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='read_receipts')).toBe(true));
 expect(request.mock.calls.some(c=>c[1]==='read_test')).toBe(false);
});
it('discovers automatically and connects without choosing or staging a conversation',async()=>{
 const bind=vi.fn();render(<SourceExecutorSetup source={source(false)} demo={false} onBind={bind} createHost={createHost}/>);await ready();
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect']);
 expect(screen.getByText('Research mail')).toBeTruthy();
 expect(screen.queryAllByRole('combobox').filter(node=>!node.closest('details'))).toHaveLength(0);
 expect(screen.getByText('Advanced: execution and diagnostics').closest('details')?.open).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Connect'}));
 await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='configure')).toBe(true));
 expect(bind).not.toHaveBeenCalled();expect(request.mock.calls.some(c=>c[1]==='read_test')).toBe(false);
});
it('reuses the saved execution, reconciles on Test and never submits again while pending',async()=>{
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();
 const test=screen.getByRole('button',{name:'Test access'});expect((test as HTMLButtonElement).disabled).toBe(false);
 fireEvent.click(test);await screen.findByText('Read pending: reconcile the same request');
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect','read_receipts','read_test']);
 fireEvent.click(screen.getByRole('button',{name:'Check progress'}));
 await waitFor(()=>expect(request.mock.calls.filter(c=>c[1]==='read_receipts')).toHaveLength(2));
 expect(request.mock.calls.filter(c=>c[1]==='read_test')).toHaveLength(1);
 expect(screen.queryByText('Read verified within the receipt scope')).toBeNull();
});
it('does not dispatch a new intent when reconciliation finds an unresolved request',async()=>{
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?inspection():{receipts:[],unresolved_request:'prior-request'});
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();
 fireEvent.click(screen.getByRole('button',{name:'Test access'}));await screen.findByRole('button',{name:'Check progress'});
 expect(request.mock.calls.some(c=>c[1]==='read_test')).toBe(false);
});
it('shows an explicit friendly context choice for multiple environments and never guesses default',async()=>{
 const other={...route,profile:'another',targetProfile:'another',key:'other-route'};
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route,other]}:inspection());
 render(<SourceExecutorSetup source={source(false)} demo={false} onBind={vi.fn()} createHost={createHost}/>);
 await screen.findByRole('group',{name:'Choose the Hermes context'});
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes']);
 fireEvent.click(screen.getByRole('button',{name:'This device · research'}));await ready();
 expect(request.mock.calls.filter(c=>c[1]==='inspect')[0][2]).toBe('fixture-route');
});
it('does not fall back to another route when the saved owner is missing',async()=>{
 request.mockImplementation(async()=>({routes:[{...route,profile:'default',targetProfile:'default',key:'default-route'}]}));
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('Hermes unavailable'));
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes']);
 expect((screen.getByRole('button',{name:'Connect'}) as HTMLButtonElement).disabled).toBe(true);
});
it('keeps loading visible, handles empty routes and never creates execution on opening',async()=>{
 let resolve!: (result:unknown)=>void;
 request.mockReturnValue(new Promise(done=>{resolve=done;}));
 render(<SourceExecutorSetup source={source(false)} demo={false} onBind={vi.fn()} createHost={createHost}/>);
 await waitFor(()=>expect(request).toHaveBeenCalled());expect(screen.getByRole('status').textContent).toBe('Finding connections…');
 await act(async()=>resolve({routes:[]}));
 await waitFor(()=>expect(screen.getByRole('status').textContent).toBe('Hermes unavailable'));
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes']);
});
it('ignores stale discovery after changing the source and closes the old host',async()=>{
 let resolve!: (result:unknown)=>void;
 request.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
 const view=render(<SourceExecutorSetup source={source(false)} demo={false} onBind={vi.fn()} createHost={createHost}/>);
 await waitFor(()=>expect(request).toHaveBeenCalledTimes(1));
 view.rerender(<SourceExecutorSetup source={{...source(false),source_id:'source-b',title:'Second source'}} demo={false} onBind={vi.fn()} createHost={createHost}/>);
 await ready();await act(async()=>resolve({routes:[{...route,key:'stale-route'}]}));
 expect(screen.getByText('Second source')).toBeTruthy();expect(close).toHaveBeenCalledTimes(1);
 expect(request.mock.calls.filter(c=>c[1]==='inspect').every(c=>c[0].source_id==='source-b')).toBe(true);
});
it('keeps execution selection in Advanced and stages only the declared owner for review',async()=>{
 const bind=vi.fn();render(<SourceExecutorSetup source={source(false)} demo={false} onBind={bind} createHost={createHost}/>);await ready();advanced();
 const button=screen.getByText('Use this executor in source settings') as HTMLButtonElement;expect(button.disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Existing native conversation'),{target:{value:'stored-fixture'}});fireEvent.click(button);expect(bind).toHaveBeenCalledWith(execution);
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect']);
});
it('opens a discovered native toolset through official settings without provider-specific controls',async()=>{
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?{...inspection(),toolsets:[{name:'new-native-tools',enabled:false,tools:[]}]}:{});
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await ready();advanced();
 fireEvent.change(screen.getByLabelText('Official settings'),{target:{value:'toolset:new-native-tools'}});fireEvent.click(screen.getByRole('button',{name:'Connect'}));
 await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='configure' && c[4]==='toolset:new-native-tools')).toBe(true));
});
