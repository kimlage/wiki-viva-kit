// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {configureLanguage} from '../data/i18n';
import type {SourceEntity,SourceExecutionBinding} from '../types';
import {SourceExecutorSetup} from './SourceExecutorSetup';
const execution:SourceExecutionBinding={connection_id:'fixture',profile:'research',target_profile:'research',method:'native_session',stored_session_id:'stored-fixture'};
const route={connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local',key:'fixture-route'};
const sha='a'.repeat(64),config='b'.repeat(64),request=vi.fn();
const createHost=()=>({request,connect:async()=>{},close:()=>{}});
const source=(bound=true)=>({source_id:'source-a',context:'research',access:{binding_sha256:sha},access_policy:bound?{execution}:{}} as SourceEntity);
const inspection=()=>({binding:{config_sha256:config},sessions:[{id:'stored-fixture',title:'Existing context'}],accounts:[]});
beforeEach(()=>{configureLanguage('en');request.mockReset();request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?inspection():a==='read_receipts'?{receipts:[]}:{status:'pending',source_id:'source-a',binding_sha256:sha,config_sha256:config,execution});});
afterEach(cleanup);
async function inspect(){fireEvent.click(screen.getByText('Find Hermes executors'));await waitFor(()=>expect((screen.getByLabelText('Environment / profile') as HTMLSelectElement).disabled).toBe(false));fireEvent.change(screen.getByLabelText('Environment / profile'),{target:{value:route.key}});fireEvent.click(screen.getByText('Inspect methods in this executor'));await screen.findByLabelText('Existing native conversation');}
it('requires an explicit existing conversation and stages only its context binding',async()=>{
 const bind=vi.fn();render(<SourceExecutorSetup source={source(false)} demo={false} onBind={bind} createHost={createHost}/>);await inspect();
 const button=screen.getByText('Use this executor in source settings') as HTMLButtonElement;expect(button.disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Existing native conversation'),{target:{value:'stored-fixture'}});fireEvent.click(button);expect(bind).toHaveBeenCalledWith(execution);
 expect(request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect']);
});
it('requires reconciliation before a native turn and keeps its pending result blocked',async()=>{
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await inspect();
 const read=screen.getByText('Test read in the saved executor') as HTMLButtonElement;expect(read.disabled).toBe(true);
 fireEvent.click(screen.getByText('Reload receipts for this binding'));await waitFor(()=>expect(read.disabled).toBe(false));fireEvent.click(read);
 await screen.findByText('Read pending: reconcile the same request');expect(read.disabled).toBe(true);
 expect(screen.queryByText('Read verified within the receipt scope')).toBeNull();
});
it('native trace displays arbitrary actual tool names without claiming account or read permission',async()=>{
 request.mockImplementation(async(_s,a)=>a==='routes'?{routes:[route]}:a==='inspect'?inspection():{receipts:[{status:'native_trace_observed',source_id:'source-a',binding_sha256:sha,config_sha256:config,execution,tool_refs:[{id:'tool-1',name:'unseen_source_operation'}]}]});
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await inspect();fireEvent.click(screen.getByText('Reload receipts for this binding'));
 await screen.findByText('unseen_source_operation · tool-1');expect(screen.queryByText('Read verified within the receipt scope')).toBeNull();
 fireEvent.click(screen.getByText('Open native conversation and approvals'));await waitFor(()=>expect(request.mock.calls.some(c=>c[1]==='open_native')).toBe(true));
});
it('inspection refreshes configuration while native submissions remain pinned',async()=>{
 let configNow=config;
 request.mockImplementation(async(_s,a,_route,expected)=>{
  if(a==='routes')return {routes:[route]};if(a==='inspect')return {...inspection(),binding:{config_sha256:configNow}};
  if(expected!==configNow)throw new Error('source_configuration_changed');return {receipts:[]};
 });
 render(<SourceExecutorSetup source={source()} demo={false} onBind={vi.fn()} createHost={createHost}/>);await inspect();configNow='c'.repeat(64);
 fireEvent.click(screen.getByText('Reload receipts for this binding'));await screen.findByRole('alert');fireEvent.click(screen.getByText('Inspect methods in this executor'));await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull());
 expect(request.mock.calls.filter(c=>c[1]==='inspect').slice(-1)[0][3]).toBeUndefined();
 fireEvent.click(screen.getByText('Reload receipts for this binding'));await waitFor(()=>expect(request.mock.calls.filter(c=>c[1]==='read_receipts').slice(-1)[0][3]).toBe(configNow));
});
