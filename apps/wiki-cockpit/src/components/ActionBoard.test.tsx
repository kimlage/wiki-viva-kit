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
