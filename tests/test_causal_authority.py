"""Synthetic pre-existing documentary authority; never account authorization."""
import copy
import json

import pytest

from test_causal_review import authored, contract, make, run
from wiki_core.causal_review import census
from wiki_core.document_records import digest, edge_digest, project_records, sections, structured_digest


def fixture(*, graph_change=None, proof_change=None, qualify=True, complete_sections=False,
            receiving_section=False):
    base, current, changed = make()
    for graph in (base, current):
        graph['documents']['authority'] = (
            '# Review authority\n\nThe review rule already applies to policy. '
            'The older policy wording does not impose a second human approval.\n')
        graph['nodes']['authority'] = dict(updated_at='2026-10-26', stale_after_days=30)
        graph['edges'].append(dict(source='consumer', target='authority', type='source_ref',
            direction='directed', basis='frontmatter', path='consumer', field='source_refs'))
    citation = dict(source='policy', target='authority', type='markdown_link',
        direction='directed', basis='markdown_body', path='policy', field='body',
        body_line=5, body_offset=2)
    current['documents']['policy'] += '[Applicable review](authority).\n'
    current['edges'].append(citation)
    if graph_change:
        graph_change(base, current, changed)
    spec = contract(base, current)
    unit = 'policy'
    if receiving_section:
        for graph in (base, current):
            graph['documents']['policy'] = graph['documents']['policy'].replace('# policy\n', '# policy\n\n## Procedure\n')
        spec = contract(base, current)
        before_section = sections(base['documents']['policy'])[1]['Procedure'][2]
        after_section = sections(current['documents']['policy'])[1]['Procedure'][2]
        spec['documents'].append(dict(path='policy', records=[dict(id='procedure', heading='Procedure',
            independent=True, rationale='Complete synthetic procedure.', epistemic_status='decision',
            recorded_on='2026-10-26', context_records=[], base_sha256=digest(before_section),
            current_sha256=digest(after_section))]))
        spec['document_modes']['policy'] = 'h2_v1'
        unit = 'policy::record:procedure'
    authority = 'authority'
    supports = [dict(node=authority, sha256=digest(base['documents'][authority]),
                     complete_text=base['documents'][authority])]
    if complete_sections:
        text = '# Authority\n\n## Rule\n\nPolicy uses independent review.\n\n## Limits\n\nNo new account or execution grants.\n'
        for graph in (base, current):
            graph['documents']['authority'] = text
        spec = contract(base, current)
        parts = sections(text)[1]
        spec['documents'].append(dict(path='authority', records=[dict(id=heading.lower(),
            heading=heading, independent=True, rationale='Complete applicable rule and mandatory limits.',
            epistemic_status='decision', recorded_on='2026-10-26',
            context_records=['limits'] if heading == 'Rule' else [],
            base_sha256=digest(parts[heading][2]), current_sha256=digest(parts[heading][2]))
            for heading in ('Rule', 'Limits')]))
        spec['document_modes']['authority'] = 'h2_v1'
        for origin, graph in (('base', base), ('current', current)):
            for edge in graph['edges']:
                if edge['target'] == 'authority':
                    spec['bindings'].append(dict(origin=origin, edge_sha256=edge_digest(edge),
                        target_record='rule', consumed_sha256=digest(parts['Rule'][2]),
                        rationale='Consume the complete rule with its mandatory Limits context.'))
        authority = 'authority::record:rule'
        supports = [dict(node='authority::record:' + h.lower(), sha256=digest(parts[h][2]),
                         complete_text=parts[h][2]) for h in ('Rule', 'Limits')]
    pc, pb, seeds, _ = project_records(current, base, changed, spec)
    inventory = census(pc, pb, seeds)
    eid = next(key for key, row in inventory['edges'].items()
               if row['origin'] == 'current' and row['consumer'] == unit
               and row['prerequisite'] == authority and row['edge'].get('body_line') == 5)
    proof = dict(schema_version='wiki_base_authority_applicability.v1',
        unit=unit, unit_base_sha256=(digest(base['documents']['policy']) if unit=='policy'
                                    else pb['nodes'][unit]['record_sha256']),
        authority=authority, authority_base_sha256=supports[0]['sha256'],
        authority_document='authority', authority_document_sha256=digest(base['documents']['authority']),
        supporting_units=supports,
        applicability_reason='The complete prior rule explicitly applies to policy. It remains in force unchanged.')
    if proof_change:
        proof_change(proof)
    data = (json.dumps(proof, sort_keys=True) + '\n').encode()
    qualification = dict(edge_id=eid, evidence_id='prior-applicability',
        evidence_sha256=digest(data.decode()), reason='Review confirms prior applicability, not a new permission.')
    spec, inputs = authored(base, current, changed, spec=spec,
        mutate=(lambda p: p.update(base_authority_citations=[qualification])) if qualify else None)
    if qualify:
        for origin in ('base', 'current'):
            spec['artifacts'].append(dict(origin=origin, id='prior-applicability',
                                         path='prior-applicability.json', sha256=qualification['evidence_sha256']))
            inputs[(origin, 'prior-applicability')] = data
    return base, current, changed, spec, inputs


def reseal_review(spec, inputs):
    plan = spec['causal_review']
    key = ('current', plan['review_evidence'])
    receipt = json.loads(inputs[key])
    receipt['plan_sha256'] = structured_digest({k: v for k, v in plan.items() if k != 'review_evidence'})
    inputs[key] = (json.dumps(receipt, sort_keys=True) + '\n').encode()
    next(a for a in spec['artifacts'] if (a['origin'], a['id']) == key)['sha256'] = digest(inputs[key].decode())


def test_exact_reviewed_prior_authority_citation_preserves_debt_and_graph():
    args = fixture()
    before = copy.deepcopy(args[:3])
    result = run(*args)
    assert result['ok']
    assert any(r['path'] == 'tail' and r['state'] == 'stale' for r in result['unrelated_debt'])
    assert args[:3] == before
    assert len(args[0]['edges']) + 1 == len(args[1]['edges'])


def test_equal_context_reachability_alone_does_not_prove_prior_applicability():
    with pytest.raises(ValueError, match='interpretation'):
        run(*fixture(qualify=False))


@pytest.mark.parametrize('field', ['unit', 'unit_base_sha256', 'authority', 'authority_base_sha256',
    'authority_document', 'authority_document_sha256'])
def test_applicability_proof_is_bound_to_exact_prior_units(field):
    with pytest.raises(ValueError, match='prior units'):
        run(*fixture(proof_change=lambda p: p.update({field: 'different'})))


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(supporting_units=[]),
    lambda p: p['supporting_units'][0].update(complete_text='An incomplete quotation.'),
    lambda p: p['supporting_units'][0].update(node='policy'),
    lambda p: p['supporting_units'].append(copy.deepcopy(p['supporting_units'][0])),
    lambda p: p.update(applicability_reason=''),
])
def test_incomplete_or_misidentified_applicability_evidence_fails(mutation):
    with pytest.raises(ValueError, match='applicability'):
        run(*fixture(proof_change=mutation))


def test_current_only_evidence_cannot_replace_the_sealed_base_proof():
    b, c, changed, spec, inputs = fixture()
    spec['artifacts'] = [a for a in spec['artifacts'] if (a['origin'], a['id']) != ('base', 'prior-applicability')]
    inputs.pop(('base', 'prior-applicability'))
    with pytest.raises(ValueError, match='sealed immutable'):
        run(b, c, changed, spec, inputs)


def test_changed_authority_is_not_preexisting_unchanged_applicability():
    with pytest.raises(ValueError, match='completely intact'):
        run(*fixture(graph_change=lambda b, c, s: c['documents'].update(authority='# New permission\n')))


@pytest.mark.parametrize('change', ['remove', 'role', 'multiplicity', 'extra-scope', 'unqualified-citation', 'direct'])
def test_qualification_cannot_hide_other_interpretation_changes(change):
    def mutate(b, c, changed):
        if change == 'remove':
            c['edges'] = [e for e in c['edges'] if not (e['source'] == 'consumer' and e['target'] == 'authority')]
        elif change == 'role':
            c['edges'][0]['field'] = 'claims'
        elif change == 'multiplicity':
            c['edges'].append(copy.deepcopy(c['edges'][0]))
        elif change == 'extra-scope':
            c['documents']['new-fact'] = '# New premise\n'
            c['nodes']['new-fact'] = dict(updated_at='2026-10-26', stale_after_days=30)
            c['edges'].append(dict(source='authority', target='new-fact', type='source_ref',
                direction='directed', basis='frontmatter', path='authority', field='source_refs'))
        elif change == 'unqualified-citation':
            e = copy.deepcopy(c['edges'][-1]); e['body_line'] = 6; e['body_offset'] = 12
            c['edges'].append(e)
        else:
            c['documents']['consumer'] += '[New direct citation](authority).\n'
            changed.add('consumer')
    with pytest.raises(ValueError, match='interpretation'):
        run(*fixture(graph_change=mutate))


def test_stale_authority_is_still_a_required_factual_blocker():
    def mutate(b, c, changed):
        for g in (b, c):
            g['nodes']['authority']['updated_at'] = '2026-01-01'
    result = run(*fixture(graph_change=mutate))
    assert not result['ok']
    assert any(r['path'] == 'authority' and r['state'] == 'stale' for r in result['blockers'])


def test_qualification_changed_after_review_is_rejected():
    b, c, changed, spec, inputs = fixture()
    spec['causal_review']['base_authority_citations'][0]['reason'] = 'Different proposed interpretation.'
    with pytest.raises(ValueError, match='not independent'):
        run(b, c, changed, spec, inputs)


def test_unused_or_duplicate_citation_is_not_silent_authority():
    for duplicate in (False, True):
        b, c, changed, spec, inputs = fixture()
        plan = spec['causal_review']
        if duplicate:
            plan['base_authority_citations'].append(copy.deepcopy(plan['base_authority_citations'][0]))
        else:
            plan['dispositions'] = []
        reseal_review(spec, inputs)
        with pytest.raises(ValueError, match='unused|duplicate'):
            run(b, c, changed, spec, inputs)


def test_prior_applicability_requires_independent_semantic_review():
    b, c, changed, spec, inputs = fixture()
    key = ('current', spec['causal_review']['review_evidence'])
    receipt = json.loads(inputs[key])
    receipt.update(decision='pending', unresolved_findings=['Prior rule may have an unmet condition.'])
    inputs[key] = json.dumps(receipt).encode()
    next(a for a in spec['artifacts'] if (a['origin'], a['id']) == key)['sha256'] = digest(inputs[key].decode())
    with pytest.raises(ValueError, match='not independent'):
        run(b, c, changed, spec, inputs)


def test_complete_selected_authority_preserves_mandatory_local_context():
    assert run(*fixture(complete_sections=True))['ok']
    with pytest.raises(ValueError, match='omits complete authority context'):
        run(*fixture(complete_sections=True, proof_change=lambda p: p['supporting_units'].pop()))


def test_old_qualified_occurrence_cannot_cover_a_new_ambiguous_occurrence():
    def mutate(b, c, changed):
        # The proof names line 5, which is already present in BASE. The actual
        # addition at line 6 is deliberately not qualified.
        b['edges'].append(copy.deepcopy(c['edges'][-1]))
        new = copy.deepcopy(c['edges'][-1]); new.update(body_line=6, body_offset=12)
        c['edges'].append(new)
    with pytest.raises(ValueError, match='interpretation'):
        run(*fixture(graph_change=mutate))


@pytest.mark.parametrize('kind', ['record_context_reference', 'navigation_link'])
@pytest.mark.parametrize('receiving_section', [False, True])
def test_prior_nonfactual_citation_cannot_be_reclassified_as_a_new_one(kind, receiving_section):
    def mutate(b, c, changed):
        prior = copy.deepcopy(c['edges'][-1])
        prior.update(type=kind, authored_role='navigation')
        b['edges'].append(prior)
    with pytest.raises(ValueError, match='role reclassification'):
        run(*fixture(graph_change=mutate, receiving_section=receiving_section))


def test_authority_proof_does_not_close_a_second_seed():
    def mutate(b, c, changed):
        for graph in (b, c):
            graph['documents']['other'] = '# Independent factual premise\n'
            graph['nodes']['other'] = dict(updated_at='2026-10-26', stale_after_days=30)
            graph['edges'].append(dict(source='consumer', target='other', type='source_ref',
                direction='directed', basis='frontmatter', path='consumer', field='source_refs'))
        c['documents']['other'] += 'A substantive second change.\n'
        changed.add('other')
    b, c, changed, spec, inputs = fixture(graph_change=mutate)
    bare = copy.deepcopy(spec); bare.pop('causal_review')
    pc, pb, seeds, _ = project_records(c, b, changed, bare, artifact_inputs=inputs)
    inventory = census(pc, pb, seeds)
    spec['causal_review']['dispositions'] = [d for d in spec['causal_review']['dispositions']
        if inventory['obligations'][d['obligation_id']]['seed'] != 'other']
    reseal_review(spec, inputs)
    result = run(b, c, changed, spec, inputs)
    assert not result['ok']
    assert any(r['seed'] == 'other' and r['reason'] == 'causal_missing' for r in result['blockers'])
