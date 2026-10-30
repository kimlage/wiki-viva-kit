import datetime as dt
from copy import deepcopy
from wiki_core.information_use import assess_information_use

NOW=dt.datetime(2026,10,30,12,tzinfo=dt.timezone.utc)

def graph():
    return {'verification_coverage': {'claim':True}, 'nodes':{'claim':{'page_type':'claim','confidence':'confirmed','verified_at':'2026-10-30',
                             'evidence_refs':['evidence']}},
            'documents':{'claim':'A specific observed fact.','evidence':'Preserved source observation.'},
            'errors':[], 'edges':[{'source':'action','target':'claim','type':'operational_prerequisite',
                                 'requirement':{'fields':['body'],'temporal':'current','max_age_days':1}}]}

def test_specific_claim_keeps_day_precision_and_explicit_evidence():
    r=assess_information_use(graph(),'action',now=NOW)
    assert r['ready'] and r['requirements'][0]['verification_precision']=='day'
    assert r['requirements'][0]['verified_at']=='2026-10-30'

def test_discovery_timestamp_is_not_claim_verification():
    g=graph();g['nodes']['claim'].pop('verified_at');g['nodes']['claim']['sync']={'last_sync_success_at':'2026-10-30'}
    assert not assess_information_use(g,'action',now=NOW)['ready']

def test_future_expired_missing_unconfirmed_and_catalogue_are_not_usable():
    for delta in [{'verified_at':'2026-10-31'},{'verified_at':'2026-01-01'}, {'confidence':'inferred'},
                  {'evidence_refs':['absent']},{'page_type':'source'},{'valid_to':'2026-10-29'},
                  {'verified_at':'2026-10'},{'valid_from':'2026-11-01'}]:
        g=graph();g['nodes']['claim'].update(delta)
        assert not assess_information_use(g,'action',now=NOW)['ready'],delta

def test_historical_use_can_inspect_an_old_observation_without_freshening_it():
    g=graph();g['nodes']['claim']['verified_at']='2026-01-01';g['edges'][0]['requirement']['temporal']='historical'
    assert assess_information_use(g,'action',now=NOW)['ready']
    assert g['nodes']['claim']['verified_at']=='2026-01-01'

def test_validity_is_rechecked_when_time_advances():
    g=graph();g['nodes']['claim']['valid_to']='2026-10-30T12:00:05Z'
    assert assess_information_use(g,'action',now=NOW)['ready']
    assert not assess_information_use(g,'action',now=NOW+dt.timedelta(seconds=10))['ready']

def test_factual_change_after_verification_is_not_covered_by_retained_date(tmp_path):
    import subprocess
    from wiki_core.information_use import verification_covers_content
    def git(*args):subprocess.run(['git',*args],cwd=tmp_path,check=True,capture_output=True)
    git('init');git('config','user.name','Synthetic');git('config','user.email','fixture@example.invalid')
    (tmp_path/'evidence.md').write_text('Specific captured observation.\n')
    p=tmp_path/'claim.md';p.write_text('---\nverified_at: 2026-10-30\nlabel: first\n---\nObserved fact.\n')
    git('add','.');git('commit','-qm','fact and verification')
    assert verification_covers_content(tmp_path,'claim.md',['body'],['evidence.md'])
    p.write_text(p.read_text().replace('label: first','label: other'))
    git('add','.');git('commit','-qm','editorial label')
    assert verification_covers_content(tmp_path,'claim.md',['body'],['evidence.md'])
    p.write_text(p.read_text().replace('Observed fact.','Different fact.'))
    git('add','.');git('commit','-qm','changed fact without verification')
    assert not verification_covers_content(tmp_path,'claim.md',['body'],['evidence.md'])

def test_current_use_without_revision_coverage_is_not_verified():
    g=graph();g.pop('verification_coverage')
    assert not assess_information_use(g,'action',now=NOW)['ready']


def test_self_evidence_or_closed_claim_cycle_cannot_certify_current_use():
    g=graph();g['nodes']['claim']['evidence_refs']=['claim']
    result=assess_information_use(g,'action',now=NOW)
    assert not result['ready']
    assert 'information_evidence_self_reference' in result['requirements'][0]['blockers']
    g=graph();g['nodes']['other']={'page_type':'claim','evidence_refs':['claim']}
    g['nodes']['claim']['evidence_refs']=['other'];g['documents']['other']='Another assertion.'
    result=assess_information_use(g,'action',now=NOW)
    assert not result['ready'] and 'information_evidence_closed_claim_cycle' in result['requirements'][0]['blockers']
    g['nodes']['other']['evidence_refs'].append('evidence')
    assert assess_information_use(g,'action',now=NOW)['ready']


def test_missing_provenance_never_enters_a_filesystem_read(tmp_path,monkeypatch):
    import wiki_core.information_use as information
    g=graph();g['nodes']['claim']['evidence_refs']=['../../unapproved.md']
    def forbidden(*args,**kwargs):raise AssertionError('Unloaded evidence must not be read')
    monkeypatch.setattr(information,'verification_covers_content',forbidden)
    bound=information.bind_verification_coverage(tmp_path,g)
    assert not assess_information_use(bound,'action',now=NOW)['ready']


def test_malformed_evidence_or_page_id_returns_an_impediment_instead_of_crashing(tmp_path):
    from wiki_core.information_use import bind_verification_coverage
    for invalid in [{'unexpected':'mapping'},['nested','list']]:
        g=graph();g['nodes']['claim']['evidence_refs']=[invalid]
        g['nodes']['claim']['page_id']=invalid
        bound=bind_verification_coverage(tmp_path,g)
        assert not assess_information_use(bound,'action',now=NOW)['ready']


def test_nested_type_change_cannot_inherit_an_unchanged_verification(tmp_path):
    from tests.test_freshness_impact import git,commit
    from wiki_core.information_use import verification_covers_content
    git(tmp_path,'init','-q');git(tmp_path,'config','user.name','Synthetic')
    git(tmp_path,'config','user.email','fixture@example.invalid')
    (tmp_path/'evidence.md').write_text('Captured observation.\n')
    claim=tmp_path/'claim.md';claim.write_text('---\nverified_at: 2026-10-30\n'
        'confidence: confirmed\nevidence_refs: [evidence.md]\nobservation: {flag: false}\n---\nA fact.\n')
    commit(tmp_path)
    assert verification_covers_content(tmp_path,'claim.md',['observation'],['evidence.md'])
    claim.write_text(claim.read_text().replace('flag: false','flag: 0'));commit(tmp_path)
    assert not verification_covers_content(tmp_path,'claim.md',['observation'],['evidence.md'])


def test_replacing_evidence_or_promoting_confidence_requires_verification(tmp_path):
    import subprocess
    from wiki_core.information_use import verification_covers_content
    def git(*args):subprocess.run(['git',*args],cwd=tmp_path,check=True,capture_output=True)
    git('init');git('config','user.name','Synthetic');git('config','user.email','fixture@example.invalid')
    for name in ['first.md','other.md']:(tmp_path/name).write_text('Captured evidence.\n')
    p=tmp_path/'claim.md';p.write_text('---\nverified_at: 2026-10-30\nconfidence: inferred\nevidence_refs: [first.md]\n---\nAn observation.\n')
    git('add','.');git('commit','-qm','original observation')
    assert verification_covers_content(tmp_path,'claim.md',['body'],['first.md'])
    p.write_text(p.read_text().replace('inferred','confirmed').replace('first.md','other.md'))
    git('add','.');git('commit','-qm','qualifiers changed without verification')
    assert not verification_covers_content(tmp_path,'claim.md',['body'],['other.md'])

def test_deleting_expired_validity_or_fact_does_not_reuse_old_verification(tmp_path):
    import subprocess
    from wiki_core.information_use import verification_covers_content
    def git(*args):subprocess.run(['git',*args],cwd=tmp_path,check=True,capture_output=True)
    git('init');git('config','user.name','Synthetic');git('config','user.email','fixture@example.invalid')
    (tmp_path/'evidence.md').write_text('Preserved observation.\n')
    original='---\nverified_at: 2026-10-30\nconfidence: confirmed\nvalid_to: 2026-10-29\nevidence_refs: [evidence.md]\n---\nObserved fact.\nA material qualification.\n'
    p=tmp_path/'claim.md';p.write_text(original);git('add','.');git('commit','-qm','original expired observation')
    for updated in [original.replace('valid_to: 2026-10-29\n',''),original.replace('A material qualification.\n','')]:
        p.write_text(updated);git('add','.');git('commit','-qm','deletion without new verification')
        assert not verification_covers_content(tmp_path,'claim.md',['body'],['evidence.md'])
