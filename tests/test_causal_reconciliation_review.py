"""Independent review counterexamples for occurrence-bound reconciliation."""
import pytest

from test_causal_review import make, contract, authored
from wiki_core.document_records import project_records, digest, edge_digest


def ref(consumer, prerequisite):
    return dict(source=consumer, target=prerequisite, type='source_ref',
                direction='directed', basis='frontmatter', path=consumer, field='source_refs')


def add_node(base, current, name, old=None, new=None):
    for graph in (base, current):
        graph['nodes'][name] = dict(updated_at='2026-10-26', stale_after_days=30)
        graph['documents'][name] = old or ('# ' + name + '\n\nExisting local duty.\n')
    if new is not None:
        current['documents'][name] = new


def request(plan, nodes):
    for item in plan['dispositions']:
        if item['disposition'] == 'no_change':
            item['reviewed_upstream_repairs'] = list(nodes)


def test_repaired_other_branch_cannot_supply_this_arrival():
    b, c, changed = make()
    add_node(b,c,'r',new='# r\n\nSubstantively repaired local duty.\n')
    add_node(b,c,'q')
    add_node(b,c,'authority')
    for graph in (b,c):
        graph['edges'] = [ref('r','policy'),ref('q','policy'),ref('consumer','r'),
                          ref('consumer','q'),ref('tail','consumer')]
    c['edges'].append(ref('r','authority'))
    changed.add('r')
    spec, inputs = authored(b,c,changed,
        select=lambda e,o: e['consumer']=='r' or
            (o['seed']=='policy' and e['consumer']=='consumer' and e['prerequisite']=='q'),
        disposition=lambda e: 'updated' if e['consumer']=='r' else 'no_change',
        mutate=lambda plan: request(plan,['r']))
    with pytest.raises(ValueError, match='same-seed substantive support'):
        project_records(c,b,changed,spec,artifact_inputs=inputs)


def test_repaired_boundary_cannot_hide_its_old_prerequisite_selector_change():
    b,c,_ = make()
    c['documents']['policy'] = b['documents']['policy']
    add_node(b,c,'r',new='# r\n\nSubstantively repaired local duty.\n')
    table='| Key | Duty |\n| --- | --- |\n| stable | Same complete local condition. |\n'
    q='# Q\n\n## First\n\n'+table+'\n## Second\n\n'+table
    add_node(b,c,'q',old=q)
    for graph in (b,c):
        graph['edges']=[ref('r','q'),ref('consumer','r'),ref('tail','consumer')]
    spec=contract(b,c)
    selectors={origin:dict(kind='table_row',container_heading_path=['Q',heading],
        header_sha256=digest('| Key | Duty |\n| --- | --- |\n'),key_column=0,
        key=dict(kind='text',value='stable'),required_match_count=1)
        for origin,heading in (('base','First'),('current','Second'))}
    row='| stable | Same complete local condition. |\n'
    spec['documents'].append(dict(path='q',records=[dict(id='entry',selectors=selectors,
        independent=True,rationale='Complete table row with exact native selector.',
        epistemic_status='decision',recorded_on='2026-10-26',context_records=[],
        base_sha256=digest(row),current_sha256=digest(row))]))
    spec['document_modes']['q']='explicit_view_v2'
    for origin,graph in (('base',b),('current',c)):
        edge=next(e for e in graph['edges'] if e['source']=='r')
        spec['bindings'].append(dict(origin=origin,edge_sha256=edge_digest(edge),target_record='entry',
            consumed_sha256=digest(row),rationale='Consumes the exact complete selected condition.'))
    spec,inputs=authored(b,c,{'r'},spec=spec,
        select=lambda e,o: o['seed']=='r' and e['consumer']=='consumer',
        mutate=lambda plan:request(plan,['r']))
    with pytest.raises(ValueError, match='same-seed substantive support'):
        project_records(c,b,{'r'},spec,artifact_inputs=inputs)


def test_reachable_but_unnecessary_repair_request_is_rejected():
    b,c,changed=make()
    for node in ('r1','r2','p'):
        add_node(b,c,node,new='# '+node+'\n\nSubstantively repaired local duty.\n')
    add_node(b,c,'authority')
    for graph in (b,c):
        graph['edges']=[ref('r1','policy'),ref('r2','policy'),ref('p','r1'),
                        ref('p','r2'),ref('consumer','p'),ref('tail','consumer')]
    c['edges'].append(ref('r1','authority'))
    changed.update({'r1','r2','p'})
    spec,inputs=authored(b,c,changed,
        select=lambda e,o:e['consumer'] in {'r1','r2','p'} or
            (o['seed']=='policy' and e['consumer']=='consumer'),
        disposition=lambda e:'no_change' if e['consumer']=='consumer' else 'updated',
        mutate=lambda plan:request(plan,['r1','r2']))
    # r1 explains the structural delta. r2 is reachable and repaired but its
    # interpretation is already equal, so including it must not count as use.
    with pytest.raises(ValueError, match='unused'):
        project_records(c,b,changed,spec,artifact_inputs=inputs)


def transitive_pair(depth, cycle=False):
    b, c, _ = make()
    c['documents']['policy'] = b['documents']['policy']
    nodes = ['r', *['q' + str(i) for i in range(depth)]]
    for node in nodes:
        add_node(b, c, node, new='# ' + node + '\n\nSubstantively repaired local duty.\n')
    add_node(b, c, 'authority')
    add_node(b, c, 'alternate')
    leaf = nodes[-1]
    for graph in (b, c):
        graph['edges'] = [ref('consumer', 'r'), ref('tail', 'consumer'),
                          ref('r', 'authority'), ref('r', 'alternate'), ref(leaf, 'authority')]
        graph['edges'].extend(ref(parent, child) for parent, child in zip(nodes, nodes[1:]))
        if cycle:
            graph['edges'].append(ref(leaf, 'r'))
    return b, c, set(nodes), leaf


@pytest.mark.parametrize('depth', [1, 3])
@pytest.mark.parametrize('cycle', [False, True])
@pytest.mark.parametrize('mutation', ['remove', 'multiplicity', 'reclassify', 'retarget',
                                     'direction', 'context_add', 'context_remove', 'ambiguous_relocation'])
def test_repaired_frontier_preserves_transitive_relations_not_only_reachable_scopes(depth, cycle, mutation):
    b, c, changed, leaf = transitive_pair(depth, cycle)
    for graph in (b, c):
        if mutation in {'multiplicity', 'ambiguous_relocation'}:
            old = next(e for e in graph['edges'] if e['source'] == leaf and e['target'] == 'authority')
            old.update(type='markdown_link', basis='markdown_body', field='body',
                       section='Original', body_line=3, body_offset=0)
            graph['edges'].append(dict(old, body_line=4))
        elif mutation == 'context_remove':
            graph['edges'].append(dict(ref(leaf, 'authority'), field='context_records'))
    target = next(e for e in c['edges'] if e['source'] == leaf and e['target'] == 'authority')
    if mutation in {'remove', 'multiplicity'}:
        c['edges'].remove(target)
    elif mutation == 'reclassify':
        target['type'] = 'navigation_link'
    elif mutation == 'retarget':
        target['target'] = 'alternate'
    elif mutation == 'direction':
        target['direction'] = 'undirected'
    elif mutation == 'context_remove':
        c['edges'] = [e for e in c['edges'] if e.get('field') != 'context_records']
    elif mutation == 'ambiguous_relocation':
        for edge in c['edges']:
            if edge['source'] == leaf and edge['target'] == 'authority':
                edge['section'] = 'Reworded'
    else:
        # Even adding a mandatory context to an old consumed unit changes the
        # inherited contract; the alternate r->authority path retains scopes.
        c['edges'].append(dict(ref(leaf, 'authority'), field='context_records'))
    spec, inputs = authored(b, c, changed,
        select=lambda e, o: e['consumer'] in changed | {'consumer'},
        disposition=lambda e: 'no_change' if e['consumer'] == 'consumer' else 'updated',
        mutate=lambda plan: request(plan, ['r']))
    with pytest.raises(ValueError, match='same-seed substantive support'):
        project_records(c, b, changed, spec, artifact_inputs=inputs)


@pytest.mark.parametrize('cycle', [False, True])
@pytest.mark.parametrize('kind', ['citation', 'relocation', 'stale_new_context'])
def test_transitive_preservation_keeps_reviewed_additions_and_unique_relocations(cycle, kind):
    from test_causal_review import run
    b, c, changed, leaf = transitive_pair(3, cycle)
    if kind == 'relocation':
        for graph, section in ((b, 'Original'), (c, 'Reworded')):
            edge = next(e for e in graph['edges'] if e['source'] == leaf and e['target'] == 'authority')
            edge.update(type='markdown_link', basis='markdown_body', field='body',
                        section=section, body_line=3, body_offset=0)
    else:
        for node in ('new-authority', 'new-context'):
            add_node(b, c, node, old='# ' + node + '\n\nComplete additional premise.\n')
        # These documents already exist, but their factual context was not
        # consumed by the repaired frontier in BASE.
        for graph in (b, c):
            graph['edges'].append(dict(ref('new-authority', 'new-context'), field='context_records'))
        c['edges'].append(ref(leaf, 'new-authority'))
        if kind == 'stale_new_context':
            for graph in (b, c):
                graph['nodes']['new-context']['updated_at'] = '2026-01-01'
    spec, inputs = authored(b, c, changed,
        select=lambda e, o: e['consumer'] in changed | {'consumer'},
        disposition=lambda e: 'no_change' if e['consumer'] == 'consumer' else 'updated',
        mutate=lambda plan: request(plan, ['r']))
    result = run(b, c, changed, spec, inputs)
    if kind == 'stale_new_context':
        assert not result['ok']
        assert any(row['path'] == 'new-context' and row['reason'] == 'required_dependency'
                   for row in result['blockers'])
    else:
        assert result['ok']
    assert any(row['path'] == 'tail' for row in result['unrelated_debt'])
