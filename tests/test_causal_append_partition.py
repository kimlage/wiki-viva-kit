"""An appended independent unit cannot reinterpret any preexisting byte."""
import json

import pytest

from test_causal_review import authored, contract, make, run
from wiki_core.document_records import digest, edge_digest, project_records


def middle_observation(*, qualified=True, unreviewed_sibling=False):
    from test_causal_review import TODAY
    from wiki_core.causal_review import census, pair_digest
    from wiki_core.document_records import sections, structured_digest
    b, c, changed, spec = append_pair('explicit_view_v2')
    added = c['documents']['log'][len(b['documents']['log']):]
    c['documents']['log'] = b['documents']['log'].replace('## Prior', added + '## Prior', 1)
    entry = spec['documents'][-1]['records'][0]
    source = b'{"observed_fact":"a new independent event occurred"}'
    inputs = {('current', 'measurement'): source}
    spec['artifacts'].append(dict(origin='current', id='measurement', path='measurement.json', sha256=digest(source.decode())))
    entry['current_evidence'] = ['measurement']
    if qualified:
        entry['current_observation'] = 'new-record-proof'
    if unreviewed_sibling:
        c['documents']['log'] = c['documents']['log'].replace('Retained complete', 'Changed complete')
        spec['documents'][-1]['records'].append(dict(id='prior', independent=True,
            rationale='A separate changed assertion requires its own review.', epistemic_status='observation',
            recorded_on=TODAY.isoformat(), context_records=[],
            selectors={o:dict(kind='h2', heading='Prior') for o in ('base','current')},
            **{o+'_sha256':digest(sections(g['documents']['log'])[1]['Prior'][2]) for o,g in (('base',b),('current',c))}))
        # The original consumer is deliberately rebound to the intact header,
        # so it cannot claim the changed sibling itself is unchanged.
        for binding in spec['bindings']:
            if binding.get('target_record') == 'remainder':
                binding['consumed_sha256'] = digest('# Log\n\n')
    for origin, g in (('base', b), ('current', c)):
        spec[origin+'_documents_sha256'] = {p:digest(t) for p,t in g['documents'].items()}
    if qualified:
        proof = dict(schema_version='wiki_record_observation.v1', document='log', record_id='new-event',
            document_sha256=digest(c['documents']['log']), record_sha256=entry['current_sha256'],
            declaration_sha256=structured_digest({k:v for k,v in entry.items() if k!='current_observation'}),
            observed_on=TODAY.isoformat(), scope='The complete inserted event only; no sibling is revalidated.', contexts={},
            sources=[dict(id='measurement', sha256=digest(source.decode()), purpose='Retained independent event evidence.')],
            review=dict(author='writer', reviewer='independent-reader', decision='approved', unresolved_findings=[]))
        raw=json.dumps(proof,sort_keys=True).encode();inputs['current','new-record-proof']=raw
        spec['artifacts'].append(dict(origin='current',id='new-record-proof',path='observation.json',sha256=digest(raw.decode())))
    pc,pb,seeds,_=project_records(c,b,changed,spec,artifact_inputs=inputs)
    inventory=census(pc,pb,seeds)
    decisions=[]
    for oid, obligation in inventory['obligations'].items():
        edge=inventory['edges'][obligation['edge_id']]
        if edge['consumer']=='log::record:remainder':
            decisions.append(dict(obligation_id=oid,disposition='no_change',
                reason='Exact current policy change leaves the complete old remainder intact; the inserted event has its own proof.'))
    plan=dict(schema_version='wiki_causal_review.v1',author='writer',pair_sha256=pair_digest(pc,pb,seeds),
        census_sha256=structured_digest(inventory),dispositions=decisions,review_evidence='causal-review')
    spec['causal_review']=plan
    receipt=dict(schema_version='wiki_causal_review_receipt.v1',author='writer',reviewer='independent-reader',
        decision='approved',plan_sha256=structured_digest({k:v for k,v in plan.items() if k!='review_evidence'}),unresolved_findings=[])
    raw=json.dumps(receipt,sort_keys=True).encode();inputs['current','causal-review']=raw
    spec['artifacts'].append(dict(origin='current',id='causal-review',path='causal-review.json',sha256=digest(raw.decode())))
    return b,c,changed,spec,inputs


def test_reviewed_middle_insertion_keeps_intact_remainder_but_not_whole():
    from test_causal_review import TODAY
    from wiki_core.freshness_impact import evaluate_impact
    b,c,changed,spec,inputs=middle_observation()
    pc,pb,seeds,_=project_records(c,b,changed,spec,artifact_inputs=inputs)
    result=evaluate_impact(pc,pb,seeds,today=TODAY)
    assert any(r['consumer']=='log::record:remainder' for r in result['causal_review']['approved_boundaries'])
    assert not result['ok'] and any(r['path']=='whole' for r in result['blockers'])
    assert pc['verified_record_shapes']['log::record:remainder'] != pb['verified_record_shapes']['log::record:remainder']


@pytest.mark.parametrize('fault', ['no_observation', 'unreviewed_sibling', 'proof_mutation'])
def test_middle_insertion_cannot_qualify_another_delta_or_forge_geometry(fault):
    from test_causal_review import TODAY
    from wiki_core.freshness_impact import evaluate_impact
    b,c,changed,spec,inputs=middle_observation(qualified=fault!='no_observation',unreviewed_sibling=fault=='unreviewed_sibling')
    if fault=='proof_mutation':
        pc,pb,seeds,_=project_records(c,b,changed,spec,artifact_inputs=inputs)
        for g in (pc,pb):g['verified_h2_partition_changes']['log']['changed_components']=[]
        with pytest.raises(ValueError,match='inputs changed'):
            evaluate_impact(pc,pb,seeds,today=TODAY)
    else:
        with pytest.raises(ValueError,match='identical complete consumer'):
            project_records(c,b,changed,spec,artifact_inputs=inputs)


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
