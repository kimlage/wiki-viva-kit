// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ActionBoard } from './ActionBoard';
import type { SnapshotLoadResult } from '../application/ports';
import { boardPages } from '../data/actionBoard';
import type { PageRecord } from '../types';
afterEach(cleanup);
const action = (id: string, state = 'open', priority = 'normal') => ({id, title:id, path:`memories/${id}.md`, context:'system', page_type:'action', content_sha256:'a'.repeat(64), work:{state, priority, next_action:'Read evidence', owner_ref:'coordinator'}} as unknown as PageRecord);
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
