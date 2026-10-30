from wiki_core.source_state import merge_review_requests, review_attempt_allowed


def request(consumer='action',condition='source-old'):
    return dict(scope='statement',fields=['body'],consumer=consumer,condition=condition,priority='active')


def test_shared_source_scope_batches_consumers_without_another_queue():
    state={'source_id':'synthetic-source','streams':{'main':{'cursor':'preserved'}}}
    merged=merge_review_requests(state,'main',[request(),request('other-action')])
    assert merged['streams']['main']['cursor']=='preserved'
    rows=merged['streams']['main']['review_requests'];assert len(rows)==1
    assert rows[0]['consumers']==['action','other-action']
    assert merge_review_requests(merged,'main',[request(),request('other-action')])==merged
    assert state['streams']['main']=={'cursor':'preserved'}


def test_same_blocker_never_repeats_without_changed_condition_and_budget():
    r=merge_review_requests({'source_id':'source','streams':{}},'main',[request()])['streams']['main']['review_requests'][0]
    assert not review_attempt_allowed(r,'source-old',max_attempts=0)
    assert review_attempt_allowed(r,'source-old',max_attempts=1)
    r['attempts']=[{'condition':'source-old','status':'blocked'}]
    assert not review_attempt_allowed(r,'source-old',max_attempts=2)
    assert review_attempt_allowed(r,'new-export',max_attempts=2)
    assert not review_attempt_allowed(r,'new-export',max_attempts=1)


def test_reprojection_preserves_satisfied_obligation_and_releases_old_consumers():
    state=merge_review_requests({'source_id':'source','streams':{}},'main',[request()])
    row=state['streams']['main']['review_requests'][0];row['status']='verified'
    row['attempts']=[{'condition':'source-old','status':'verified'}]
    assert merge_review_requests(state,'main',[request()])==state
    inactive=merge_review_requests(state,'main',[])['streams']['main']['review_requests'][0]
    assert inactive['status']=='inactive' and inactive['consumers']==[] and inactive['attempts']==row['attempts']
    changed=merge_review_requests(state,'main',[request(condition='changed-fact')])['streams']['main']['review_requests'][0]
    assert changed['status']=='review_pending' and changed['attempts']==row['attempts']
