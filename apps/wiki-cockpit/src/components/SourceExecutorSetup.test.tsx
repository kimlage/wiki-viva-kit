// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { configureLanguage } from '../data/i18n';
import type { SourceEntity, SourceExecutionBinding } from '../types';
const mocks = vi.hoisted(()=>({request:vi.fn(),close:vi.fn(),connect:vi.fn()}));
const createHost=()=>({request:mocks.request,close:mocks.close,connect:mocks.connect});
import {SourceExecutorSetup} from './SourceExecutorSetup';
const execution:SourceExecutionBinding={connection_id:'fixture',profile:'research',target_profile:'research',method:'local_git',provider_id:'',resource_ref:'wiki_repository'};
const route={connectionId:'fixture',profile:'research',targetProfile:'research',mode:'local',key:'fixture-route'};
const sha='a'.repeat(64),config='b'.repeat(64);
function source(bound=true):SourceEntity {return {source_id:'source-a',source_kind:'repository',context:'research',access:{binding_sha256:sha},access_policy:bound?{execution}:undefined} as SourceEntity;}
function receipt(status='read_verified'){return {source_id:'source-a',binding_sha256:sha,config_sha256:config,execution,status,valid_until:new Date(Date.now()+60000).toISOString(),identity:{status:'not_applicable'},observed_permissions:['git.metadata.read']};}
beforeEach(()=>{configureLanguage('en');mocks.request.mockReset();mocks.connect.mockResolvedValue(undefined);mocks.request.mockImplementation(async (_s,action)=>action==='routes'?{routes:[route]}:action==='inspect'?{binding:{config_sha256:config,resource_options:[{id:'wiki_repository',target:'/synthetic/wiki'}]},managed_available:false,providers:[]}:action==='read_receipts'?{receipts:[]}:receipt());});
afterEach(()=>{cleanup();vi.useRealTimers();});
async function inspect(){fireEvent.click(screen.getByText('Find Hermes executors'));await waitFor(()=>expect((screen.getByLabelText('Environment / profile') as HTMLSelectElement).disabled).toBe(false));fireEvent.change(screen.getByLabelText('Environment / profile'),{target:{value:route.key}});fireEvent.click(screen.getByText('Inspect methods in this executor'));await screen.findByText(/\/synthetic\/wiki/);}
it('requires saved binding and receipt reconciliation before a read, including after reopening',async()=>{
 const first=render(<SourceExecutorSetup createHost={createHost} source={source()} demo={false} onBind={vi.fn()}/>);await inspect();
 const read=screen.getByText('Test read in the saved executor') as HTMLButtonElement;
 expect(read.disabled).toBe(true);fireEvent.click(screen.getByText('Reload receipts for this binding'));await waitFor(()=>expect(read.disabled).toBe(false));fireEvent.click(read);await screen.findByText('Read verified within the receipt scope');
 expect(mocks.request.mock.calls.filter(c=>c[1]==='read_test')).toHaveLength(1);
 first.unmount();render(<SourceExecutorSetup createHost={createHost} source={source()} demo={false} onBind={vi.fn()}/>);await inspect();expect((screen.getByText('Test read in the saved executor') as HTMLButtonElement).disabled).toBe(true);
});
it('first setup stages only an explicit repository/profile declaration and does not read or grant',async()=>{
 const bind=vi.fn();render(<SourceExecutorSetup createHost={createHost} source={source(false)} demo={false} onBind={bind}/>);await inspect();
 fireEvent.click(screen.getByText('Use this executor in source settings'));expect(bind).toHaveBeenCalledWith(execution);
 expect((screen.getByText('Test read in the saved executor') as HTMLButtonElement).disabled).toBe(true);
 expect(mocks.request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect']);
});
it('unknown results remain blocked while a pending receipt exists',async()=>{
 mocks.request.mockImplementation(async(_s,action)=>action==='routes'?{routes:[route]}:action==='inspect'?{binding:{config_sha256:config,resource_options:[{id:'wiki_repository',target:'/synthetic/wiki'}]}}:action==='read_receipts'?{receipts:[receipt('pending')]}:receipt());
 render(<SourceExecutorSetup createHost={createHost} source={source()} demo={false} onBind={vi.fn()}/>);await inspect();fireEvent.click(screen.getByText('Reload receipts for this binding'));await screen.findByText('Read pending: reconcile the same request');expect((screen.getByText('Test read in the saved executor') as HTMLButtonElement).disabled).toBe(true);
});

it('chooses a managed account by exact id and alias; catalogue support never proves its identity',async()=>{
 const bind=vi.fn();
 mocks.request.mockImplementation(async(_s,action)=>action==='routes'?{routes:[route]}:action==='inspect'?{binding:{config_sha256:config},managed_available:true,providers:[{id:'gmail',method:'managed_connector',label:'gmail'}],accounts:[{id:'fixture-account',connector:'gmail',alias:'research',label:'Research account',status:'active'}]}:{});
 const gmail={...source(false),source_kind:'account',platform:'gmail'} as SourceEntity;
 render(<SourceExecutorSetup createHost={createHost} source={gmail} demo={false} onBind={bind}/>);
 fireEvent.click(screen.getByText('Find Hermes executors'));await waitFor(()=>expect((screen.getByLabelText('Environment / profile') as HTMLSelectElement).disabled).toBe(false));
 fireEvent.change(screen.getByLabelText('Environment / profile'),{target:{value:route.key}});fireEvent.click(screen.getByText('Inspect methods in this executor'));
 await screen.findByLabelText('Access method');fireEvent.change(screen.getByLabelText('Access method'),{target:{value:'managed_connector'}});
 fireEvent.change(screen.getByLabelText('Configured provider'),{target:{value:'gmail'}});
 const save=screen.getByText('Use this executor in source settings') as HTMLButtonElement;expect(save.disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Named account in this executor'),{target:{value:'fixture-account'}});fireEvent.click(save);
 expect(bind).toHaveBeenCalledWith({...execution,method:'managed_connector',provider_id:'gmail',resource_ref:'',account_id:'fixture-account',account_alias:'research'});
 expect(screen.queryByText(/Read verified within/)).toBeNull();
 expect(mocks.request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect']);
});

it('invalid receipt expiry never displays a verified read',async()=>{
 mocks.request.mockImplementation(async(_s,action)=>action==='routes'?{routes:[route]}:action==='inspect'?{binding:{config_sha256:config,resource_options:[{id:'wiki_repository',target:'/synthetic/wiki'}]}}:action==='read_receipts'?{receipts:[{...receipt(),valid_until:'invalid'}]}:{});
 render(<SourceExecutorSetup createHost={createHost} source={source()} demo={false} onBind={vi.fn()}/>);await inspect();fireEvent.click(screen.getByText('Reload receipts for this binding'));
 await screen.findByText('Recorded read: evidence expired');expect(screen.queryByText('Read verified within the receipt scope')).toBeNull();
});

it('stages browser-controller binding without a hidden provider or starting a read',async()=>{
 const bind=vi.fn();render(<SourceExecutorSetup createHost={createHost} source={source(false)} demo={false} onBind={bind}/>);await inspect();
 fireEvent.change(screen.getByLabelText('Access method'),{target:{value:'browser_controller'}});
 expect(screen.queryByLabelText('Configured provider')).toBeNull();
 const save=screen.getByText('Use this executor in source settings') as HTMLButtonElement;
 expect(save.disabled).toBe(false);fireEvent.click(save);
 expect(bind).toHaveBeenCalledWith({...execution,method:'browser_controller',resource_ref:''});
 expect(mocks.request.mock.calls.map(c=>c[1])).toEqual(['routes','inspect']);
 expect(screen.queryByText('Read verified within the receipt scope')).toBeNull();
});

it('inspection discovers the current configuration while reads remain pinned and reconciled',async()=>{
 let currentConfig=config;
 mocks.request.mockImplementation(async(_s,action,_route,expectedConfig)=>{
  if(action==='routes')return {routes:[route]};
  if(expectedConfig && expectedConfig!==currentConfig)throw new Error('source_configuration_changed');
  if(action==='inspect')return {binding:{config_sha256:currentConfig,resource_options:[{id:'wiki_repository',target:'/synthetic/wiki'}]}};
  if(action==='read_receipts')return {receipts:[]};
  return {...receipt(),config_sha256:currentConfig};
 });
 render(<SourceExecutorSetup createHost={createHost} source={source()} demo={false} onBind={vi.fn()}/>);await inspect();
 fireEvent.click(screen.getByText('Reload receipts for this binding'));
 const read=screen.getByText('Test read in the saved executor') as HTMLButtonElement;
 await waitFor(()=>expect(read.disabled).toBe(false));
 currentConfig='c'.repeat(64);
 fireEvent.click(read);await screen.findByRole('alert');
 expect(mocks.request.mock.calls.filter(c=>c[1]==='read_test').slice(-1)[0]?.[3]).toBe(config);
 fireEvent.click(screen.getByText('Inspect methods in this executor'));
 await waitFor(()=>expect(screen.queryByRole('alert')).toBeNull());
 expect(mocks.request.mock.calls.filter(c=>c[1]==='inspect').slice(-1)[0]?.[3]).toBeUndefined();
 expect(read.disabled).toBe(true);
 fireEvent.click(screen.getByText('Reload receipts for this binding'));await waitFor(()=>expect(read.disabled).toBe(false));
 expect(mocks.request.mock.calls.filter(c=>c[1]==='read_receipts').slice(-1)[0]?.[3]).toBe(currentConfig);
 fireEvent.click(read);await screen.findByText('Read verified within the receipt scope');
 expect(mocks.request.mock.calls.filter(c=>c[1]==='read_test').slice(-1)[0]?.[3]).toBe(currentConfig);
});
