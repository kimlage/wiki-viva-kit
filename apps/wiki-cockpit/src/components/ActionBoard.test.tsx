// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ActionBoard } from './ActionBoard';
import type { SnapshotLoadResult } from '../application/ports';
import { boardPages } from '../data/actionBoard';
import type { PageRecord } from '../types';
afterEach(cleanup);
const action = (id: string, state = 'open', priority = 'normal') => ({id, title:id, path:`memories/${id}.md`, context:'system', page_type:'action', content_sha256:'a'.repeat(64), work:{state, priority, next_action:'Read evidence', owner_ref:'coordinator'}} as unknown as PageRecord);

it('recovers one stale content read from a fresh snapshot without writing',async()=>{
  const revision=(id:string,hash:string)=>({source:'/api/snapshot',runtime:{mode:'local_operator'},bundle:{manifest:{repo:{language:'en'},snapshot_id:id},pages:{pages:[{...action('Async task'),content_sha256:hash.repeat(64)}]},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult);
  const operator={
    loadSnapshotBundle:vi.fn().mockResolvedValueOnce(revision('revision-a','a')).mockResolvedValue(revision('revision-b','b')),
    loadPageContent:vi.fn().mockResolvedValueOnce({ok:false,error:'page changed since snapshot; refresh required',error_code:'snapshot_revision_mismatch',snapshot_id:'revision-b',expected_snapshot_id:'revision-a'})
      .mockResolvedValue({ok:true,snapshot_id:'revision-b',body:'# Current evidence',frontmatter:{},source_refs:[],resolved_links:[]})
  };
  const save=vi.fn();
  render(<ActionBoard operator={operator} save={save}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Async task/}));
  expect(await screen.findByText('Current evidence')).toBeTruthy();
  expect(operator.loadSnapshotBundle).toHaveBeenCalledTimes(2);
  expect(operator.loadPageContent.mock.calls.map(call=>call[1].snapshotId)).toEqual(['revision-a','revision-b']);
  expect(save).not.toHaveBeenCalled();
});

const readSnapshot=(id:string,pages=[action('Async task')])=>({source:'/api/snapshot',runtime:{mode:'local_operator'},bundle:{manifest:{repo:{language:'en'},snapshot_id:id},pages:{pages},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult);
const staleRead=(expected:string,current:string)=>({ok:false,error:'page changed since snapshot; refresh required',error_code:'snapshot_revision_mismatch',expected_snapshot_id:expected,snapshot_id:current,read_status:409});

it('stops after one read recovery and exposes only sanitized revision diagnostics',async()=>{
  const operator={
    loadSnapshotBundle:vi.fn().mockResolvedValueOnce(readSnapshot('revision-a')).mockResolvedValue(readSnapshot('revision-b')),
    loadPageContent:vi.fn().mockResolvedValueOnce(staleRead('revision-a','revision-b')).mockResolvedValue(staleRead('revision-b','revision-c'))
  };
  const save=vi.fn();
  render(<ActionBoard operator={operator} save={save}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Async task/}));
  const alert=await screen.findByRole('alert');
  expect(alert.textContent).toContain('The wiki changed while opening');
  expect(alert.getAttribute('data-read-error-code')).toBe('snapshot_revision_mismatch');
  expect(alert.getAttribute('data-read-http-status')).toBe('409');
  expect(alert.getAttribute('data-expected-snapshot-id')).toBe('revision-b');
  expect(alert.getAttribute('data-current-snapshot-id')).toBe('revision-c');
  expect(screen.getByLabelText('Page and evidence').getAttribute('data-read-snapshot-id')).toBe('revision-b');
  expect(operator.loadSnapshotBundle).toHaveBeenCalledTimes(2);
  expect(operator.loadPageContent).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('button',{name:'Save to wiki'})).toBeNull();
  expect(save).not.toHaveBeenCalled();
});

it.each(['forbidden_route','content_integrity_mismatch','untrusted_code'])('does not retry or reveal response details for %s',async(errorCode)=>{
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(readSnapshot('revision-a')),loadPageContent:vi.fn().mockResolvedValue({ok:false,error_code:errorCode,error:'untrusted response detail',read_status:'untrusted response detail',read_error_type:'untrusted response detail'})};
  const save=vi.fn();
  render(<ActionBoard operator={operator} save={save}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Async task/}));
  const alert=await screen.findByRole('alert');
  expect(alert.getAttribute('data-read-error-code')).toBe(errorCode==='untrusted_code'?'content_unavailable':errorCode);
  expect(document.body.textContent).not.toContain('untrusted response detail');
  expect(document.body.innerHTML).not.toContain('untrusted response detail');
  expect(document.body.innerHTML).not.toContain('untrusted_code');
  expect(operator.loadSnapshotBundle).toHaveBeenCalledTimes(1);
  expect(operator.loadPageContent).toHaveBeenCalledTimes(1);
  expect(save).not.toHaveBeenCalled();
});

it('does not refresh a demo into the local operator after a revision error',async()=>{
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(readSnapshot('revision-a')),loadPageContent:vi.fn().mockResolvedValue(staleRead('revision-a','revision-b'))};
  render(<ActionBoard operator={operator} save={vi.fn()} demo/>);
  fireEvent.click(await screen.findByRole('button',{name:/Async task/}));
  await screen.findByRole('alert');
  expect(operator.loadSnapshotBundle).toHaveBeenCalledTimes(1);
  expect(operator.loadSnapshotBundle).toHaveBeenCalledWith({demo:true});
});

it('ignores a late revision conflict from a page the user already left',async()=>{
  let finishOldRead:(value:ReturnType<typeof staleRead>)=>void=()=>{};
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(readSnapshot('revision-a',[action('First task'),action('Second task')])),loadPageContent:vi.fn().mockImplementation(async(id:string)=>id==='First task'?await new Promise(resolve=>{finishOldRead=resolve;}):{ok:true,snapshot_id:'revision-a',body:'Second evidence',frontmatter:{}})};
  const save=vi.fn();
  render(<ActionBoard operator={operator} save={save}/>);
  fireEvent.click(await screen.findByRole('button',{name:/First task/}));
  await waitFor(()=>expect(operator.loadPageContent).toHaveBeenCalledTimes(1));
  const oldSignal=operator.loadPageContent.mock.calls[0][1].signal as AbortSignal;
  fireEvent.click(screen.getByRole('button',{name:/Second task/}));
  await screen.findByText('Second evidence');
  expect(oldSignal.aborted).toBe(true);
  await act(async()=>finishOldRead(staleRead('revision-a','revision-b')));
  expect(screen.getByText('Second evidence')).toBeTruthy();
  expect(operator.loadSnapshotBundle).toHaveBeenCalledTimes(1);
  expect(save).not.toHaveBeenCalled();
});

it('requires the refreshed coordinator map before a recovered card can save with its new hash',async()=>{
  const task={...action('Async task'),content_sha256:'b'.repeat(64)};
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValueOnce(readSnapshot('revision-a')).mockImplementation(async()=>readSnapshot('revision-b',[task])),loadPageContent:vi.fn().mockResolvedValueOnce(staleRead('revision-a','revision-b')).mockResolvedValue({ok:true,snapshot_id:'revision-b',body:'Current evidence',frontmatter:{}})};
  const map=(id:string,hash:string)=>({schema_version:'wiki_coordination.v1',configured:true,snapshot_id:id,profiles:[{id:'research',label:'Research',scope:'Synthetic',action_ids:['Async task']}],actions:[{action_id:'Async task',coordinator:'research',content_sha256:hash.repeat(64)}]});
  let finishMap:(value:ReturnType<typeof map>)=>void=()=>{};
  const loadCoordination=vi.fn().mockResolvedValueOnce(map('revision-a','a')).mockImplementation(()=>new Promise(resolve=>{finishMap=resolve;}));
  const save=vi.fn().mockResolvedValue(undefined);
  render(<ActionBoard operator={operator} save={save} loadCoordination={loadCoordination}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Async task/}));
  await screen.findByText('Current evidence');
  expect(screen.getByLabelText('Next step').closest('fieldset')?.disabled).toBe(true);
  expect(screen.queryByRole('button',{name:'Save to wiki'})).toBeNull();
  expect(save).not.toHaveBeenCalled();
  await act(async()=>finishMap(map('revision-b','b')));
  await waitFor(()=>expect(screen.getByLabelText('Next step').closest('fieldset')?.disabled).toBe(false));
  fireEvent.change(screen.getByLabelText('Priority'),{target:{value:'high'}});
  fireEvent.click(screen.getByRole('button',{name:'Save to wiki'}));
  await waitFor(()=>expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0].expected_sha256).toBe('b'.repeat(64));
});
function setup(mode='local_operator', demo=false, save=vi.fn().mockResolvedValue(undefined)) {
  const pages=[action('Synthetic task'),action('Archived task','done'),{...action('Context page'),page_type:'context'}];
  const loaded={source:'/api/snapshot',runtime:{mode},bundle:{manifest:{repo:{language:'en'},snapshot_id:'test',generated_at:'2026-01-01'},pages:{pages},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult;
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(loaded),loadPageContent:vi.fn().mockResolvedValue({ok:true,body:'# Synthetic evidence',source_refs:[],resolved_links:[]})};
  render(<ActionBoard operator={operator} save={save} demo={demo}/>);
  return {operator,save};
}
describe('canonical action board',()=>{
  it('filters canonical action pages and preserves terminal history',()=>{
    const pages=[action('low','open','low'),action('high','blocked','urgent'),action('old','done'),{...action('not-action'),page_type:'context'}];
    expect(boardPages(pages,'','',false).map(p=>p.id)).toEqual(['high','low']);
    expect(boardPages(pages,'','old',true).map(p=>p.id)).toEqual(['old']);
    expect(boardPages(pages,'other','',true)).toEqual([]);
  });
  it('opens source content and sends a CAS priority edit, then rereads',async()=>{
    const {save,operator}=setup();
    fireEvent.click(await screen.findByRole('button',{name:/Synthetic task/}));
    await screen.findByText('Synthetic evidence');
    fireEvent.change(screen.getByLabelText('Priority'),{target:{value:'high'}});
    fireEvent.click(screen.getByRole('button',{name:'Save to wiki'}));
    await waitFor(()=>expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({page_ref:'memories/Synthetic task.md',expected_sha256:'a'.repeat(64),next_state:'open',priority:'high',next_action:'Read evidence'});
    await waitFor(()=>expect(operator.loadSnapshotBundle).toHaveBeenCalledTimes(2));
  });
  it('refuses sample fallback on a real wiki URL',async()=>{
    setup('sample_fallback');
    expect((await screen.findByRole('alert')).textContent).toContain('No sample data was substituted');
    expect(screen.queryByRole('button',{name:/Synthetic task/})).toBeNull();
  });
  it('keeps demo read only and exposes completed actions only on request',async()=>{
    setup('local_operator',true);
    fireEvent.click(await screen.findByRole('button',{name:/Synthetic task/}));
    await screen.findByText('Synthetic evidence');
    expect(screen.queryByRole('button',{name:'Save to wiki'})).toBeNull();
    expect(screen.queryByRole('button',{name:/Archived task/})).toBeNull();
    fireEvent.click(screen.getByLabelText('Show completed and cancelled'));
    expect(screen.getByRole('button',{name:/Archived task/})).toBeTruthy();
  });
  it('shows stale revision conflict without claiming success',async()=>{
    const save=vi.fn().mockRejectedValue(new Error('stale_action_revision'));
    setup('local_operator',false,save);
    fireEvent.click(await screen.findByRole('button',{name:/Synthetic task/}));
    fireEvent.click(await screen.findByRole('button',{name:'Save to wiki'}));
    expect((await screen.findByRole('status')).textContent).toContain('The page changed');
  });
});

it('renders inert evidence and follows encoded canonical page links',async()=>{
  const {operator}=setup();
  operator.loadPageContent.mockResolvedValue({ok:true,body:'<style>body{display:none}</style><svg><image href="https://example.org/track" /></svg>\n\n[Related](<docs/ação pendente.md>)',source_refs:[],resolved_links:[{href:'docs/ação pendente.md',kind:'page',page_id:'Context page'}]});
  fireEvent.click(await screen.findByRole('button',{name:/Synthetic task/}));
  const link=await screen.findByRole('link',{name:'Related'});
  expect(document.querySelector('.boardMarkdown style, .boardMarkdown svg, .boardMarkdown image')).toBeNull();
  fireEvent.click(link);
  await waitFor(()=>expect(operator.loadPageContent).toHaveBeenLastCalledWith('Context page',expect.anything()));
});

it('shows the primary coordinator while preserving owner and leaving live connectivity unverified', async()=>{
  const pages=[action('Synthetic task')];
  const loaded={source:'/api/snapshot',runtime:{mode:'local_operator'},bundle:{manifest:{repo:{language:'en'},snapshot_id:'test'},pages:{pages},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult;
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(loaded),loadPageContent:vi.fn().mockResolvedValue({ok:true,body:'Evidence',source_refs:[],resolved_links:[]})};
  const loadCoordination=vi.fn().mockResolvedValue({schema_version:'wiki_coordination.v1',configured:true,snapshot_id:'test',profiles:[{id:'research',label:'Research',scope:'Synthetic',action_ids:['Synthetic task']}],actions:[{action_id:'Synthetic task',coordinator:'research',content_sha256:'a'.repeat(64)}]});
  render(<ActionBoard operator={operator} save={vi.fn()} loadCoordination={loadCoordination}/>);
  await screen.findByLabelText('Coordinator');
  fireEvent.change(screen.getByLabelText('Coordinator'),{target:{value:'research'}});
  fireEvent.click(screen.getByRole('button',{name:/Synthetic task/}));
  await screen.findByText('Evidence');
  expect(screen.getAllByText('Not verified in this interface')).toHaveLength(2);
  expect(screen.getAllByText(/Coordinator:/).length).toBeGreaterThan(0);
});

it('records changed next steps as one direction with the same CAS save',async()=>{
  const pages=[action('Synthetic task')];
  const loaded={source:'/api/snapshot',runtime:{mode:'local_operator'},bundle:{manifest:{repo:{language:'en'},snapshot_id:'test'},pages:{pages},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult;
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(loaded),loadPageContent:vi.fn().mockResolvedValue({ok:true,body:'Evidence',frontmatter:{},source_refs:[],resolved_links:[]})};
  const loadCoordination=vi.fn().mockResolvedValue({configured:true,snapshot_id:'test',profiles:[{id:'research',label:'Research',action_ids:['Synthetic task']}],actions:[{action_id:'Synthetic task',coordinator:'research',content_sha256:'a'.repeat(64)}]});
  const save=vi.fn().mockResolvedValue(undefined);
  render(<ActionBoard operator={operator} save={save} loadCoordination={loadCoordination}/>);
  await screen.findByLabelText('Coordinator');
  fireEvent.click(screen.getByRole('button',{name:/Synthetic task/}));
  fireEvent.change(await screen.findByLabelText('Next step'),{target:{value:'Review signed source'}});
  fireEvent.click(screen.getByRole('button',{name:'Save to wiki'}));
  await waitFor(()=>expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({next_action:'Review signed source',dialogue_event:{kind:'direction',text:'Review signed source',coordinator:'research'}});
});

it('blocks edits while the coordinator map is pending or unavailable',async()=>{
  const pages=[action('Synthetic task')];
  const loaded={source:'/api/snapshot',runtime:{mode:'local_operator'},bundle:{manifest:{repo:{language:'en'},snapshot_id:'test'},pages:{pages},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult;
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(loaded),loadPageContent:vi.fn().mockResolvedValue({ok:true,body:'Evidence',frontmatter:{},source_refs:[],resolved_links:[]})};
  let rejectMap: (reason: Error)=>void = ()=>{};
  const loadCoordination=()=>new Promise<never>((_resolve,reject)=>{ rejectMap=reject; });
  const save=vi.fn();
  render(<ActionBoard operator={operator} save={save} loadCoordination={loadCoordination}/>);
  fireEvent.click(await screen.findByRole('button',{name:/Synthetic task/}));
  const next=await screen.findByLabelText('Next step');
  expect(next.closest('fieldset')?.disabled).toBe(true);
  expect(screen.queryByRole('button',{name:'Save to wiki'})).toBeNull();
  rejectMap(new Error('unavailable'));
  await screen.findByText('Coordinator mapping unavailable; refresh before coordinating.');
  expect(next.closest('fieldset')?.disabled).toBe(true);
  expect(save).not.toHaveBeenCalled();
});

it('keeps read-only evidence visible when the selected card has malformed dialogue',async()=>{
  const {operator,save}=setup('static',true);
  operator.loadPageContent.mockResolvedValue({ok:true,body:'# Synthetic evidence',source_refs:[],resolved_links:[],frontmatter:{action_dialogue:[null]}} as never);
  fireEvent.click(await screen.findByRole('button',{name:/Synthetic task/}));
  expect(await screen.findByText('Synthetic evidence')).toBeTruthy();
  expect((await screen.findByRole('alert')).textContent).toContain('Invalid conversation history');
  expect(screen.queryByRole('button',{name:'Record on card'})).toBeNull();
  expect(save).not.toHaveBeenCalled();
});

it('reads a related canonical artifact and returns without writing or inferring live execution',async()=>{
  const task={...action('task','done'),title:'Review the project',work:{state:'done',priority:'normal',completion_receipt:'Assisted completion; original failure retained. /private/result.md SHA-256: abc'}};
  const artifact={...action('result'),title:'Project summary',page_type:'artifact',summary:'Assisted result with retained failure.'};
  const loaded={source:'/api/snapshot',runtime:{mode:'local_operator'},bundle:{manifest:{repo:{language:'en'},snapshot_id:'test'},pages:{pages:[task,artifact]},git:{current_branch:'wiki/test'}}} as SnapshotLoadResult;
  const operator={loadSnapshotBundle:vi.fn().mockResolvedValue(loaded),loadPageContent:vi.fn().mockImplementation(async(id:string)=>id==='task'?{ok:true,body:'Action evidence',backlinks:[{page_id:'result',page_type:'artifact'},{page_id:'file:///private/secret',page_type:'artifact'}]}:{ok:true,body:'Assisted result. Original failure retained. General automation not validated.'})};
  const save=vi.fn();
  const loadCoordination=vi.fn().mockResolvedValue({configured:true,snapshot_id:'test',executor_connected:true,executor_enabled:true,profiles:[],actions:[]});
  render(<ActionBoard operator={operator} save={save} loadCoordination={loadCoordination}/>);
  fireEvent.click(await screen.findByLabelText('Show completed and cancelled'));
  fireEvent.click(screen.getByRole('button',{name:/Review the project/}));
  fireEvent.click(await screen.findByRole('button',{name:'Read: Project summary'}));
  expect(await screen.findByText('Assisted result. Original failure retained. General automation not validated.')).toBeTruthy();
  expect(screen.queryByLabelText('Result and evidence')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Back to card'}));
  await screen.findByText('Action evidence');
  expect(screen.getAllByText('Not verified in this interface')).toHaveLength(2);
  expect(screen.getByText('Original completion record').parentElement?.textContent).toContain('Assisted completion; original failure retained.');
  expect(screen.queryByLabelText('Result evidence')).toBeNull();
  expect(screen.queryByRole('button',{name:'Save to wiki'})).toBeNull();
  expect(document.querySelector('a[href^="file:"],a[href^="/private"]')).toBeNull();
  expect(operator.loadPageContent.mock.calls.map(c=>c[0])).toEqual(['task','result','task']);
  expect(save).not.toHaveBeenCalled();
});
