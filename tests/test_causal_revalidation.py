"""Synthetic integration cases to install with the reviewed core candidate."""
import copy
import json

import pytest

from test_causal_review import authored, run, unchanged_unit_sibling_repair
from test_causal_authority import reseal_review
from wiki_core.document_records import digest, project_records, sections, structured_digest


def revalidated_pair(*, mutation=None, context=False, support=True, disposition='revalidated',
                     base_date='2026-01-01', current_date='2026-10-26', select=None, source_kind=None,
                     changed_context=False):
    b,c,changed,spec = unchanged_unit_sibling_repair('h2_v1')
    b['nodes']['consumer']['updated_at']=base_date
    c['nodes']['consumer']['updated_at']=current_date
    b['documents']['consumer']=b['documents']['consumer'].replace('2026-10-25',base_date)
    c['documents']['consumer']=c['documents']['consumer'].replace('2026-10-25',current_date)
    decl=next(d for d in spec['documents'] if d['path']=='consumer')
    if context:
        text='## Limits\n\nAccount and effect permissions are independent of this local rule.\n'
        old_text=text.replace('Account and effect permissions', 'Existing effect permissions') if changed_context else text
        b['documents']['consumer']+='\n'+old_text
        c['documents']['consumer']+='\n'+text
        decl['records'][0]['context_records']=['limits']
        decl['records'].append(dict(id='limits',heading='Limits',independent=True,
            rationale='Complete mandatory limit.',epistemic_status='decision',recorded_on='2026-10-26',
            context_records=[],base_sha256=digest(old_text),current_sha256=digest(text)))
    for origin,g in (('base',b),('current',c)):
        spec[origin+'_documents_sha256']['consumer']=digest(g['documents']['consumer'])
        decl['records'][0][origin+'_sha256']=digest(sections(g['documents']['consumer'])[1]['Specific'][2])
    unit='consumer::record:specific'
    selected=sections(c['documents']['consumer'])[1]['Specific'][2]
    proof=dict(schema_version='wiki_normative_revalidation.v1',assertion_kind='normative_rule',
        consumer=unit,base_sha256=digest(selected),current_sha256=digest(selected),complete_text=selected,
        current_document_sha256=digest(c['documents']['consumer']),checked_on=current_date,
        contexts=[dict(node='consumer::record:limits',sha256=digest(text),complete_text=text)] if context else [],
        sources=[],revalidation_reason='The complete intact rule and limits were checked against the actual local canonical policy; this is not an external current fact.')
    source=b'Canonical local rule, checked in full: the separate duty and account limits remain applicable.\n'
    if source_kind=='unit':source=selected.encode()
    if source_kind=='document':source=c['documents']['consumer'].encode()
    if source_kind=='base_document':source=b['documents']['consumer'].encode()
    if source_kind=='context':source=text.encode()
    if source_kind=='base_context':source=old_text.encode()
    proof['sources'].append(dict(evidence_id='checked-local-policy',sha256=digest(source.decode()),purpose='Actual normative authority and conditions.'))
    if mutation:mutation(b,c,changed,spec,proof)
    data=(json.dumps(proof,sort_keys=True)+'\n').encode()
    claim=dict(consumer=unit,evidence_id='normative-revalidation',evidence_sha256=digest(data.decode()),
        reason='Complete sourced revalidation of this intact normative unit; not freshness borrowed from a sibling.')
    spec,inputs=authored(b,c,changed,spec=spec,select=select or (lambda e,o:e['consumer']==unit),
        disposition=disposition,mutate=(lambda p:p.update(normative_revalidations=[claim])) if support else None)
    if support:
        for aid,value in [('checked-local-policy',source),('normative-revalidation',data)]:
            spec['artifacts'].append(dict(origin='current',id=aid,path=aid+'.json',sha256=digest(value.decode())))
            inputs['current',aid]=value
    return b,c,changed,spec,inputs


def test_real_normative_revalidation_closes_only_its_reviewed_arrivals():
    args=revalidated_pair(context=True)
    result=run(*args)
    assert any(x['consumer']=='consumer::record:specific' and x['disposition']=='revalidated'
               for x in result['causal_review']['approved_boundaries'])
    assert not result['ok']  # No approval of other raw/sibling/WHOLE obligations.
    assert args[0]['nodes']['consumer']['updated_at']=='2026-01-01'
    assert args[1]['nodes']['consumer']['updated_at']=='2026-10-26'


def test_plain_no_change_still_cannot_borrow_a_siblings_date():
    result=run(*revalidated_pair(support=False,disposition='no_change'))
    assert any(r['reason']=='causal_no_change_consumer_not_fresh' for r in result['blockers'])


def test_revalidated_requires_its_exact_source_based_proof():
    with pytest.raises(ValueError,match='revalidation'):
        run(*revalidated_pair(support=False))


@pytest.mark.parametrize('source_kind',['unit','document','base_document','context'])
def test_alias_of_reviewed_object_is_not_independent_source_evidence(source_kind):
    with pytest.raises(ValueError,match='circular normative source evidence'):
        run(*revalidated_pair(context=source_kind=='context',source_kind=source_kind))


@pytest.mark.parametrize('change',[
    lambda p:p.update(assertion_kind='current_external_fact'),
    lambda p:p.update(consumer='another::record:rule'),
    lambda p:p.update(base_sha256='0'*64),
    lambda p:p.update(current_sha256='0'*64),
    lambda p:p.update(current_document_sha256='0'*64),
    lambda p:p.update(complete_text='Only a quoted fragment.'),
    lambda p:p.update(checked_on='2026-10-25'),
    lambda p:p.update(checked_on='2026-10-27'),
    lambda p:p.update(sources=[]),
    lambda p:p['sources'][0].update(sha256='0'*64),
    lambda p:p['sources'][0].update(evidence_id='normative-revalidation'),
    lambda p:p['sources'][0].update(evidence_id='synthetic-independent-review'),
])
def test_invalid_revalidation_is_not_a_date_waiver(change):
    with pytest.raises(ValueError,match='normative|revalidation'):
        run(*revalidated_pair(mutation=lambda b,c,s,n,p:change(p)))


def test_mandatory_context_cannot_be_omitted_from_revalidation():
    with pytest.raises(ValueError,match='context'):
        run(*revalidated_pair(context=True,mutation=lambda b,c,s,n,p:p.update(contexts=[])))


def test_observation_record_cannot_be_called_normatively_revalidated():
    def mutate(b,c,s,n,p):
        next(d for d in n['documents'] if d['path']=='consumer')['records'][0]['epistemic_status']='observation'
    with pytest.raises(ValueError,match='decision record'):
        run(*revalidated_pair(mutation=mutate))


def test_factual_context_cannot_borrow_normative_revalidation():
    def mutate(b,c,s,n,p):
        next(d for d in n['documents'] if d['path']=='consumer')['records'][1]['epistemic_status']='observation'
    with pytest.raises(ValueError,match='context.*decision record'):
        run(*revalidated_pair(context=True,mutation=mutate))


def test_revalidation_does_not_hide_stale_actual_prerequisite():
    def mutate(b,c,s,n,p):
        for g in (b,c):g['nodes']['policy']['updated_at']='2026-01-01'
    result=run(*revalidated_pair(mutation=mutate))
    assert any(r['path']=='policy' and r['state']=='stale' for r in result['blockers'])


def test_revalidation_does_not_hide_changed_interpretation():
    def mutate(b,c,s,n,p):c['edges'][0]['field']='claims'
    with pytest.raises(ValueError,match='interpretation'):
        run(*revalidated_pair(mutation=mutate))


def test_revalidation_requires_unchanged_cadence_and_exemptions():
    for field,value in [('stale_after_days',900),('stale_exempt',True)]:
        def mutate(b,c,s,n,p):c['nodes']['consumer'][field]=value
        with pytest.raises(ValueError,match='cadence|exempt'):
            run(*revalidated_pair(mutation=mutate))


def test_revalidation_metadata_is_bound_by_independent_review():
    b,c,s,n,i=revalidated_pair()
    n['causal_review']['normative_revalidations'][0]['reason']='Different factual assertion.'
    with pytest.raises(ValueError,match='not independent'):
        run(b,c,s,n,i)


def test_unused_or_duplicate_revalidation_proofs_fail_closed():
    for duplicate in (False,True):
        b,c,s,n,i=revalidated_pair()
        if duplicate:n['causal_review']['normative_revalidations'].append(copy.deepcopy(n['causal_review']['normative_revalidations'][0]))
        else:n['causal_review']['dispositions']=[]
        reseal_review(n,i)
        with pytest.raises(ValueError,match='unused|duplicate'):
            run(b,c,s,n,i)


@pytest.mark.parametrize('base_date,current_date', [
    ('2026-10-25','2026-10-26'),  # Already fresh is still ordinary no_change.
    ('2026-01-01','2026-10-27'),  # A future verification cannot be admitted today.
    ('2026-01-01','2026-02-01'),  # The renewed date is itself stale.
])
def test_revalidated_only_admits_stale_to_current_fresh(base_date,current_date):
    result=run(*revalidated_pair(base_date=base_date,current_date=current_date))
    assert any(r['reason']=='causal_revalidated_consumer_not_fresh' for r in result['blockers'])
    assert not result['causal_review']['approved_boundaries']


def test_unknown_base_is_not_a_supported_revalidation():
    with pytest.raises(ValueError,match='actual renewed CURRENT date'):
        run(*revalidated_pair(base_date='unknown'))


def test_unknown_cadence_stays_blocked_even_with_a_review():
    def mutate(b,c,s,n,p):
        for g in (b,c):g['nodes']['consumer']['stale_after_days']=0
    result=run(*revalidated_pair(mutation=mutate))
    assert any(r['reason']=='causal_revalidated_consumer_not_fresh' for r in result['blockers'])


def test_source_evidence_must_be_current_not_only_historical():
    b,c,s,n,i=revalidated_pair()
    next(a for a in n['artifacts'] if a['id']=='checked-local-policy')['origin']='base'
    i['base','checked-local-policy']=i.pop(('current','checked-local-policy'))
    from wiki_core.causal_review import census, pair_digest
    plan=n.pop('causal_review')
    pc,pb,seeds,_=project_records(c,b,s,n,artifact_inputs=i)
    plan.update(pair_sha256=pair_digest(pc,pb,seeds),census_sha256=structured_digest(census(pc,pb,seeds)))
    n['causal_review']=plan;reseal_review(n,i)
    with pytest.raises(ValueError,match='sealed CURRENT evidence'):
        run(b,c,s,n,i)


def test_pending_review_does_not_admit_normative_revalidation():
    b,c,s,n,i=revalidated_pair()
    aid=n['causal_review']['review_evidence']
    receipt=json.loads(i['current',aid]);receipt['decision']='pending'
    data=(json.dumps(receipt,sort_keys=True)+'\n').encode()
    i['current',aid]=data
    next(a for a in n['artifacts'] if a['id']==aid)['sha256']=digest(data.decode())
    with pytest.raises(ValueError,match='not independent'):
        run(b,c,s,n,i)


def test_review_of_another_pair_cannot_be_replayed():
    b,c,s,n,i=revalidated_pair()
    c['documents']['policy']+='Another rule changed.\n'
    n['current_documents_sha256']['policy']=digest(c['documents']['policy'])
    with pytest.raises(ValueError,match='pair/census changed'):
        run(b,c,s,n,i)


def test_second_cause_and_cycle_need_their_own_dispositions():
    def mutate(b,c,s,n,p):
        for g in (b,c):
            g['nodes']['other']=dict(updated_at='2026-10-26',stale_after_days=30)
            g['documents']['other']='# Another real premise\n'
            # Same interpretation in both snapshots, distinct causal arrival.
            g['edges'].extend([
                dict(source='consumer',target='other',type='source_ref',direction='directed',
                     basis='frontmatter',path='consumer',field='source_refs'),
                dict(source='other',target='consumer',type='source_ref',direction='directed',
                     basis='frontmatter',path='other',field='source_refs')])
        c['documents']['other']+='A real changed fact.\n';s.add('other')
        for origin,g in (('base',b),('current',c)):
            n[origin+'_documents_sha256']['other']=digest(g['documents']['other'])
    args=revalidated_pair(mutation=mutate,
        select=lambda e,o:e['consumer']=='consumer::record:specific' and o['seed']=='policy')
    result=run(*args)
    assert any(r['seed']=='other' and r['reason']=='causal_missing' for r in result['blockers'])
    assert not result['ok']


def test_old_context_alias_is_not_independent_authority():
    with pytest.raises(ValueError,match='circular normative source evidence'):
        run(*revalidated_pair(context=True,changed_context=True,source_kind='base_context'))


def test_other_revalidation_proof_alias_is_not_source_evidence():
    b,c,s,n,i=revalidated_pair(context=True,
        select=lambda e,o:e['consumer'] in {'consumer::record:specific','consumer::record:limits'})
    first=json.loads(i['current','normative-revalidation'])
    context=first['contexts'][0]
    second=dict(first,consumer=context['node'],base_sha256=context['sha256'],
                current_sha256=context['sha256'],complete_text=context['complete_text'],contexts=[])
    second_bytes=(json.dumps(second,sort_keys=True)+'\n').encode()
    second_hash=digest(second_bytes.decode())
    for aid in ('context-revalidation','alias-of-context-revalidation'):
        n['artifacts'].append(dict(origin='current',id=aid,path=aid+'.json',sha256=second_hash))
        i['current',aid]=second_bytes
    first['sources']=[dict(evidence_id='alias-of-context-revalidation',sha256=second_hash,
                           purpose='Claimed authority that is actually another review proof.')]
    first_bytes=(json.dumps(first,sort_keys=True)+'\n').encode()
    i['current','normative-revalidation']=first_bytes
    next(a for a in n['artifacts'] if a['id']=='normative-revalidation')['sha256']=digest(first_bytes.decode())
    claims=n['causal_review']['normative_revalidations']
    claims[0]['evidence_sha256']=digest(first_bytes.decode())
    claims.append(dict(consumer=context['node'],evidence_id='context-revalidation',
                       evidence_sha256=second_hash,reason='Actual current review of the complete limits.'))
    reseal_review(n,i)
    with pytest.raises(ValueError,match='circular normative source evidence'):
        run(b,c,s,n,i)
