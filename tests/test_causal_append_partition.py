"""An appended independent unit cannot reinterpret any preexisting byte."""
import pytest

from test_causal_review import authored, contract, make, run
from wiki_core.document_records import digest, edge_digest, project_records


def append_pair(mode='h2_v1', *, mutation=None):
    b,c,changed=make()
    prior='# Log\n\n## Prior\n\nRetained complete event.\n'
    added='\n## New event\n\nNew independent event.\n'
    for g in (b,c):
        g['nodes']['log']=dict(updated_at='2026-10-26',stale_after_days=30)
        g['documents']['log']=prior
        g['edges'][0]['target']='log'
        g['edges'].append(dict(source='log',target='policy',type='source_ref',direction='directed',
                               basis='frontmatter',path='log',field='source_refs'))
        g['nodes']['whole']=dict(updated_at='2026-10-26',stale_after_days=30)
        g['documents']['whole']='# Whole log consumer\n'
        g['edges'].append(dict(source='whole',target='log',type='source_ref',direction='directed',
                               basis='frontmatter',path='whole',field='source_refs'))
    c['documents']['log']+=added;changed.add('log')
    spec=contract(b,c)
    entry=dict(id='new-event',independent=True,rationale='New complete independent event, not a rewrite of the old log.',
        epistemic_status='observation',recorded_on='2026-10-26',context_records=[],
        base_sha256=None,current_sha256=digest(added))
    if mode=='h2_v1':entry.update(heading='New event',leading_blank_lines=1)
    else:entry['selectors']={'base':None,'current':dict(kind='h2',heading='New event',leading_blank_lines=1)}
    spec['documents'].append(dict(path='log',records=[entry]));spec['document_modes']['log']=mode
    for origin,g in (('base',b),('current',c)):
        edge=next(e for e in g['edges'] if e['source']=='consumer')
        spec['bindings'].append(dict(origin=origin,edge_sha256=edge_digest(edge),target_record='remainder',
            consumed_sha256=digest(prior),rationale='Complete preexisting historical remainder, retaining every original byte.'))
    if mutation:mutation(b,c,changed,spec)
    for origin,g in (('base',b),('current',c)):
        spec[origin+'_documents_sha256']={p:digest(t) for p,t in g['documents'].items()}
    return b,c,changed,spec


@pytest.mark.parametrize('mode',['h2_v1','explicit_view_v2'])
def test_exact_append_preserves_remainder_without_clearing_whole_or_new_seed(mode):
    b,c,s,n=append_pair(mode)
    n,i=authored(b,c,s,spec=n,select=lambda e,o:e['consumer']=='log::record:remainder')
    pc,pb,seeds,_=project_records(c,b,s,n,artifact_inputs=i)
    proof=pc['verified_append_only_partitions']['log::record:remainder']
    assert proof==pb['verified_append_only_partitions']['log::record:remainder']
    assert proof['added_records']==['new-event']
    assert proof['remainder_sha256']==digest(b['documents']['log'])
    assert 'log::record:new-event' in seeds
    assert 'log' not in pc['verified_precise_component_seeds']
    if mode=='explicit_view_v2':assert 'log' in seeds
    result=run(b,c,s,n,i)
    assert any(r['consumer']=='log::record:remainder' for r in result['causal_review']['approved_boundaries'])
    assert not result['ok']  # Other WHOLE/new-unit obligations were not approved.
    assert any(r['path']=='whole' for r in result['blockers'])


@pytest.mark.parametrize('mode', ['h2_v1', 'explicit_view_v2'])
@pytest.mark.parametrize('operation', ['introduced', 'removed'])
@pytest.mark.parametrize('position', ['end', 'before'])
def test_complete_h2_updated_arrival_propagates_without_qualifying_whole(mode, operation, position):
    b, c, changed, spec = append_pair(mode)
    record = spec['documents'][-1]['records'][0]
    if position == 'before':
        added = c['documents']['log'][len(b['documents']['log']):]
        c['documents']['log'] = b['documents']['log'].replace('## Prior', added + '## Prior', 1)
    if operation == 'removed':
        b, c = c, b
        record['base_sha256'], record['current_sha256'] = record['current_sha256'], None
        if mode == 'explicit_view_v2':
            record['selectors'] = {'base': record['selectors']['current'], 'current': None}
        edge = next(e for e in b['edges'] if e['source'] == 'whole')
        spec['bindings'].append(dict(origin='base', edge_sha256=edge_digest(edge),
            target_record='new-event', consumed_sha256=record['base_sha256'],
            rationale='The BASE claim consumes the complete removed event and still needs reconciliation.'))
    for origin, graph in (('base', b), ('current', c)):
        spec[origin + '_documents_sha256'] = {p: digest(t) for p, t in graph['documents'].items()}
    spec, inputs = authored(b, c, changed, spec=spec,
        select=lambda edge, obligation: edge['consumer'] == 'log::record:new-event', disposition='updated')
    assert spec['causal_review']['dispositions']
    pc, pb, seeds, _ = project_records(c, b, changed, spec, artifact_inputs=inputs)
    absent = pb if operation == 'introduced' else pc
    assert 'log::record:new-event' not in absent['nodes']
    if mode == 'h2_v1' or (position == 'end' and operation == 'introduced'):
        assert 'log' not in pc['verified_precise_component_seeds']
    result = run(b, c, changed, spec, inputs)
    assert not result['ok']
    assert not result['causal_review']['approved_boundaries']
    assert all('precise_representation_components' not in row
               for row in result['included'] if row['path'] == 'log')
    assert any(row['path'] == 'whole' for row in result['blockers'])
    if operation == 'removed':
        assert any(row['path'] == 'whole' and row['via'] == 'log::record:new-event'
                   for row in result['causal_review']['unresolved'])


@pytest.mark.parametrize('fault',['prefix','uncovered','reference-definition','new-selects-old'])
def test_append_proof_refuses_unproved_partition_changes(fault):
    def mutate(b,c,s,n):
        record=n['documents'][-1]['records'][0]
        if fault=='prefix':
            c['documents']['log']=c['documents']['log'].replace('Retained complete','Altered historical')
        elif fault=='uncovered':
            c['documents']['log']+='\n# Uncovered section\n\nAnother assertion.\n'
            record['current_sha256']=digest('\n## New event\n\nNew independent event.\n\n')
        elif fault=='reference-definition':
            c['documents']['log']+='\n[old-reference]: different.md\n'
            record['current_sha256']=digest(c['documents']['log'][len(b['documents']['log']):])
        else:
            record.update(heading='Prior',leading_blank_lines=0,
                          base_sha256=digest('## Prior\n\nRetained complete event.\n'),
                          current_sha256=digest('## Prior\n\nRetained complete event.\n\n'))
        # This case tests the projector proof, not an authored consumption hash.
        n['bindings']=[]
    b,c,s,n=append_pair(mutation=mutate)
    pc,pb,seeds,_=project_records(c,b,s,n)
    assert not pc['verified_append_only_partitions']
    assert not pb['verified_append_only_partitions']


def test_frontmatter_cannot_forge_append_partition_proof():
    b,c,s,n=append_pair(mutation=lambda b,c,s,n:c['nodes']['log'].update(
        verified_append_only_partitions={'log::record:remainder':{'base_shape':{}}}))
    c['documents']['log']=c['documents']['log'].replace('Retained complete','Changed old')
    n['current_documents_sha256']['log']=digest(c['documents']['log']);n['bindings']=[]
    pc,pb,seeds,_=project_records(c,b,s,n)
    assert not pc['verified_append_only_partitions']


def test_append_proof_is_sealed_against_mutation_after_projection():
    from test_causal_review import TODAY
    from wiki_core.freshness_impact import evaluate_impact
    b,c,s,n=append_pair()
    n,i=authored(b,c,s,spec=n,select=lambda e,o:e['consumer']=='log::record:remainder')
    pc,pb,seeds,_=project_records(c,b,s,n,artifact_inputs=i)
    for g in (pc,pb):g['verified_append_only_partitions']['log::record:remainder']['added_records']=[]
    with pytest.raises(ValueError,match='inputs changed'):
        evaluate_impact(pc,pb,seeds,today=TODAY)
