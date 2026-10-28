// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { AdminPort } from '../application/ports';
import type { AdminPlan } from '../data/admin';
import type { PageRecord } from '../types';
import { configureLanguage, t } from '../data/i18n';
import { clearAdminSession } from '../application/adminSession';
import { ActionRuntime } from './ActionRuntime';

afterEach(()=>{cleanup();clearAdminSession();});
const action={id:'synthetic-action',content_sha256:'a'.repeat(64)} as PageRecord;
const profile={id:'research',label:'Research',scope:'Synthetic',action_ids:['synthetic-action'],runtime:{configured:true,label:'Synthetic worker'}};
function setup(over: Partial<React.ComponentProps<typeof ActionRuntime>>={}) {
  configureLanguage('en');
  const plan:AdminPlan={planId:'plan-exact',planSha:'sha256:'+'b'.repeat(64),commandId:'agents.openclaw.dispatch',title:'Dispatch this action',riskLevel:'external_write',dryRun:false,
    summary:'One action',preconditions:[],effects:{filesRead:[],filesWrite:[],externalCalls:['OpenClaw chat.send'],snapshotInvalidated:false},
    diff:'Exact reviewed mission',validation:{},undo:{available:false,kind:null},confirmation:{kind:'typed',text:'PUBLISH agents.openclaw.dispatch'}};
  const admin={planAdminCommand:vi.fn().mockResolvedValue({ok:true,plan}),executeAdminPlan:vi.fn().mockResolvedValue({ok:true,outcome:{planId:plan.planId,commandId:plan.commandId,status:'success',dryRun:false,
    output:{action_id:action.id,effect_key:'wiki-run-'+'c'.repeat(32),new_dispatch:true,status:'started'},affectedPaths:[],branch:'main',snapshotInvalidated:false,undo:{available:false,kind:null}}}),
    lockAdminSession:vi.fn(),renewAdminSession:vi.fn(),requestAdminChallenge:vi.fn(),unlockAdminSession:vi.fn()} as unknown as AdminPort;
  render(<ActionRuntime admin={admin} action={action} profile={profile} attempts={[]} disabled={false} language="en" refresh={vi.fn()} {...over}/>);
  return {admin,plan};
}
it('reviews exact card identity and message before an admitted dispatch, then offers reconciliation',async()=>{
  const {admin,plan}=setup();
  fireEvent.change(screen.getByLabelText('Exact message to the executor'),{target:{value:'Inspect synthetic status.'}});
  fireEvent.click(screen.getByRole('button',{name:'Review dispatch'}));
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenCalledWith('agents.openclaw.dispatch',{
    profile:'research',action_id:action.id,action_sha256:action.content_sha256,message:'Inspect synthetic status.'}));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
  fireEvent.change(await screen.findByLabelText(t('admin.plan.typeToConfirm',{text:plan.confirmation.text!})),{target:{value:plan.confirmation.text}});
  fireEvent.click(screen.getByRole('button',{name:t('admin.plan.execute')}));
  await waitFor(()=>expect(admin.executeAdminPlan).toHaveBeenCalledWith(plan,plan.confirmation.text));
  expect(await screen.findByText('The Gateway accepted the run. This is not task completion.')).toBeTruthy();
  fireEvent.click(screen.getAllByRole('button',{name:t('surface.close')})[0]);
  fireEvent.click(screen.getByRole('button',{name:'Reconcile existing run'}));
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenLastCalledWith('agents.openclaw.inspect',{
    profile:'research',action_id:action.id,effect_key:'wiki-run-'+'c'.repeat(32)}));
  expect(admin.executeAdminPlan).toHaveBeenCalledTimes(1);
});
it('restores run identity from server discovery without dispatching on mount',()=>{
  const {admin}=setup({attempts:[{effect_key:'wiki-run-'+'d'.repeat(32),attempted_at:'2026-01-01',has_result:false}]});
  expect(screen.getByRole('button',{name:'Reconcile existing run'})).toBeTruthy();
  expect(admin.planAdminCommand).not.toHaveBeenCalled();
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});
it('does not offer dispatch with no configured route or corrupt recovery evidence',()=>{
  const {admin}=setup({recoveryError:'openclaw_receipt_unavailable_reconcile'});
  expect(screen.queryByRole('button',{name:'Review dispatch'})).toBeNull();
  expect(screen.getByRole('status').textContent).toContain('openclaw_receipt_unavailable_reconcile');
  expect(admin.planAdminCommand).not.toHaveBeenCalled();
});

it('recovers the prepared receipt and uses native publication and independent review commands', async()=>{
  const proposal={status:'prepared' as const,head:'e'.repeat(40),proposal_head:'e'.repeat(40),approved_base:'a'.repeat(40),
    branch:'wiki/runtime-return-existing',material_path:'data/derived/existing.json',material_sha256:'f'.repeat(64)};
  const {admin}=setup({attempts:[{effect_key:'wiki-run-'+'d'.repeat(32),attempted_at:'2026-01-01',has_result:true,proposal}]});
  expect(screen.getByText('Receipt committed on the proposal branch. Independent review and integration are still required.')).toBeTruthy();
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Review publication of this commit'}));
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenCalledWith('wiki.proposal.publish',{
    expected_head:proposal.head,operation:'publish_proposal'}));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});

it('offers native adoption recovery with distinct checkout and proposal identities', async()=>{
  const proposal={status:'awaiting_adoption' as const,head:'a'.repeat(40),proposal_head:'e'.repeat(40),approved_base:'a'.repeat(40),
    branch:'main',material_path:'data/derived/existing.json',material_sha256:'f'.repeat(64)};
  const {admin}=setup({attempts:[{effect_key:'wiki-run-'+'d'.repeat(32),attempted_at:'2026-01-01',has_result:true,proposal}]});
  fireEvent.change(screen.getByLabelText('Existing PR number'),{target:{value:'7'}});
  fireEvent.click(screen.getByRole('button',{name:'Review refresh of approved content'}));
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenCalledWith('wiki.proposal.adopt',{
    expected_head:proposal.head,proposal_head:proposal.proposal_head,pr:'7'}));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});

it('keeps recovered proposal commands bound to the selected effect across two runs', async()=>{
  const proposal=(head:string)=>({status:'prepared' as const,head,proposal_head:head,approved_base:'a'.repeat(40),
    branch:'wiki/existing',material_path:'data/derived/'+head+'.json',material_sha256:'f'.repeat(64)});
  const old={effect_key:'wiki-run-'+'a'.repeat(32),attempted_at:'2026-01-01',has_result:true,proposal:proposal('b'.repeat(40))};
  const recent={effect_key:'wiki-run-'+'z'.repeat(32),attempted_at:'2026-02-01',has_result:true,proposal:proposal('e'.repeat(40))};
  const {admin}=setup({attempts:[old,recent]});
  fireEvent.click(screen.getByRole('button',{name:'Review publication of this commit'}));
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenLastCalledWith('wiki.proposal.publish',{
    expected_head:recent.proposal.head,operation:'publish_proposal'}));
  fireEvent.click(screen.getAllByRole('button',{name:t('surface.close')})[0]);
  fireEvent.click(screen.getAllByRole('button',{name:'Reconcile existing run'})[0]);
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenLastCalledWith('agents.openclaw.inspect',{
    profile:'research',action_id:action.id,effect_key:old.effect_key}));
  fireEvent.click(screen.getAllByRole('button',{name:t('surface.close')})[0]);
  fireEvent.click(screen.getByRole('button',{name:'Review publication of this commit'}));
  await waitFor(()=>expect(admin.planAdminCommand).toHaveBeenLastCalledWith('wiki.proposal.publish',{
    expected_head:old.proposal.head,operation:'publish_proposal'}));
  expect(admin.executeAdminPlan).not.toHaveBeenCalled();
});
