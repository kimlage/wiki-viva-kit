import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import git, repo, write
from tests.test_protected_ingestion import (prepared_repo, prepare, record, _result_for,
    _nested_integrator_repo, protected_source_stage)
from wiki_core.coordination_context import CoordinationBinding, PreviousRequestGrant, ProtectedCoordinationError


def grant_prior(binding, args, previous, revision):
    grant = PreviousRequestGrant(executor=args['context_id'], integrator=args.get('artifact_context', args['context_id']),
        source_ref=args['source_ref'], source_id=previous['source_id'], request_id=previous['request_id'],
        policy_revision=revision)
    return replace(binding, previous_request_grants=(grant,))


def advance(root, path='beta/unrelated.md'):
    write(root, path, '# Unrelated synthetic change\n')
    git(root, 'add', path); git(root, 'commit', '-qm', 'unrelated folder')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return git(root, 'rev-parse', 'HEAD')


def test_host_environment_pins_exact_previous_grant():
    grant = {'executor': 'alpha', 'integrator': '.', 'source_ref': 'alpha/source.txt',
             'source_id': 'source-synthetic', 'request_id': 'a' * 64, 'policy_revision': 'b' * 40}
    env = {'WIKI_COORDINATION_ALLOWED_CONTEXTS': 'alpha,.',
           'WIKI_COORDINATION_PREVIOUS_REQUEST_GRANTS': json.dumps([grant])}
    binding = CoordinationBinding.from_environment(env)
    assert binding.previous_request_grants == (PreviousRequestGrant(**grant),)
    with pytest.raises(ValueError):
        CoordinationBinding.from_environment({**env, 'WIKI_COORDINATION_ALLOWED_CONTEXTS': '.'})
    with pytest.raises(ValueError):
        CoordinationBinding.from_environment({**env, 'WIKI_COORDINATION_PREVIOUS_REQUEST_GRANTS': json.dumps([grant, grant])})


def test_old_revision_claim_is_only_historical_review_candidate(prepared_repo):
    root, _ = prepared_repo
    write(root, 'AGENTS.md', '# Synthetic root\nRecord the exact policy_revision shown as a claim.\n')
    git(root, 'add', 'AGENTS.md'); git(root, 'commit', '-qm', 'selected instruction')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD'); sha = git(root, 'rev-parse', 'HEAD')
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    result = {**_result_for(before['request']), 'claims': ['The policy revision is ' + sha]}
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    cache = root / 'data/derived/wiki/.wiki-viva-protected/llm-cache'
    old_path = cache / (result['cache_key'] + '.json'); old_bytes = old_path.read_bytes()
    new_sha = advance(root)
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    row = pending['request']['chunks'][0]
    assert row['result_exists'] is False
    binding = grant_prior(binding, args, before, sha)
    reviewed = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
        previous_request_id=before['request_id'], candidate_chunk_ids=[row['chunk_id']])
    assert reviewed['request_id'] == pending['request_id']
    assert reviewed['request']['chunks'][0]['result_exists'] is False
    assert reviewed['request']['pending_llm_calls'] > 0
    review = reviewed['historical_review']
    assert review['status'] == 'review_needed' and review['unavailable_chunk_ids'] == []
    candidate = review['candidates'][0]
    assert candidate['status'] == 'review_needed' and candidate['origin']['policy_revision'] == sha
    assert candidate['origin']['authority_metadata_changed'] is False
    assert candidate['origin']['request_id'] == before['request_id']
    assert candidate['result'] == result and sha in candidate['result']['claims'][0]
    assert new_sha not in candidate['result']['claims'][0]
    with pytest.raises(ValueError):
        record(root, binding, **{**args, 'approved_revision': new_sha}, source_id=reviewed['source_id'],
               request_id=reviewed['request_id'], results=[candidate['result']])
    assert old_path.read_bytes() == old_bytes
    assert not (cache / (row['cache_key'] + '.json')).exists()


@pytest.mark.parametrize('change', ['instruction', 'source', 'read_grant'])
def test_changed_selected_input_or_redundant_scope_candidate(prepared_repo, change):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    result = _result_for(before['request'])
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    binding = grant_prior(binding, args, before, sha)
    if change == 'instruction':
        write(root, 'AGENTS.md', '# Changed selected instruction\n'); git(root, 'add', 'AGENTS.md')
    elif change == 'source':
        write(root, 'source.txt', 'Changed synthetic source text.\n'); git(root, 'add', 'source.txt')
    else:
        config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
        config['context_access']['.']['policy']['read'].append('source.txt')
        write(root, 'wiki.config.yaml', yaml.safe_dump(config)); git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'change selected input or grant'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    new_sha = git(root, 'rev-parse', 'HEAD')
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    row = pending['request']['chunks'][0]
    current = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
        previous_request_id=before['request_id'], candidate_chunk_ids=[row['chunk_id']])
    assert current['historical_review']['status'] == ('review_needed' if change == 'read_grant' else 'unavailable')
    if change == 'read_grant':
        assert current['historical_review']['candidates'][0]['origin']['authority_metadata_changed'] is True
    assert current['request']['chunks'][0]['result_exists'] is False


@pytest.mark.parametrize('change', ['unrelated', 'selected_bilateral_grant'])
def test_nested_integrator_needs_matching_grants_for_candidate(prepared_repo, change):
    root, _ = prepared_repo; sha = _nested_integrator_repo(root)
    binding = CoordinationBinding(('alpha', '.'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='alpha', approved_revision=sha, entry_folder='alpha', entry_index='alpha/index.md',
                source_ref='alpha/source.txt', artifact_context='.')
    before = prepare(root, binding, **args, source_context='alpha')
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'],
           results=[_result_for(before['request'])]); binding = grant_prior(binding, args, before, sha)
    if change == 'unrelated':
        new_sha = advance(root)
    else:
        config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
        for party, side in [('alpha', 'exports'), ('.', 'imports')]:
            next(item for item in config['context_access'][party][side] if item['selector'] == 'alpha/source.txt')['expires'] = '2098-01-01'
        write(root, 'wiki.config.yaml', yaml.safe_dump(config)); git(root, 'add', 'wiki.config.yaml')
        git(root, 'commit', '-qm', 'change source grant'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        new_sha = git(root, 'rev-parse', 'HEAD')
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha')
    row = pending['request']['chunks'][0]
    current = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='alpha',
        previous_request_id=before['request_id'], candidate_chunk_ids=[row['chunk_id']])
    assert current['historical_review']['status'] == ('review_needed' if change == 'unrelated' else 'unavailable')
    assert current['request']['chunks'][0]['result_exists'] is False


def test_prior_request_of_other_executor_never_opened_without_host_grant(prepared_repo, monkeypatch):
    root, _ = prepared_repo
    _nested_integrator_repo(root)
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['.']['exports'] = copy.deepcopy(config['context_access']['.']['exports'])
    config['context_access']['alpha']['imports'] = copy.deepcopy(config['context_access']['alpha']['imports'])
    config['context_access']['.']['imports'] = copy.deepcopy(config['context_access']['.']['imports'])
    config['context_access']['alpha']['exports'] = copy.deepcopy(config['context_access']['alpha']['exports'])
    def rule(p, c, path, cls):
        return {'from_context':p, 'to_context':c, 'selector':path, 'use':'interpretation', 'classification':cls, 'expires':'2099-01-01'}
    source_alpha = rule('.', 'alpha', 'source.txt', 'source')
    config['context_access']['.']['exports'].append(source_alpha)
    config['context_access']['alpha']['imports'].append(source_alpha)
    config['context_access']['alpha']['policy']['read'].append('source.txt')
    root_to_beta = [rule('.', 'beta', 'AGENTS.md', 'context'), rule('.', 'beta', 'source.txt', 'source')]
    beta_to_root = [rule('beta', '.', 'beta/AGENTS.md', 'context'), rule('beta', '.', 'beta/index.md', 'context')]
    config['context_access']['.']['exports'].extend(root_to_beta)
    config['context_access']['.']['imports'].extend(beta_to_root)
    config['context_access']['beta'] = {'owner':'beta synthetic', 'policy':{'read':['self','AGENTS.md','source.txt'], 'write':['self'], 'capabilities':[], 'deny':{}, 'publication':[]}, 'imports':root_to_beta, 'exports':beta_to_root}
    write(root,'wiki.config.yaml',yaml.safe_dump(config))
    git(root,'add','wiki.config.yaml'); git(root,'commit','-qm','synthetic bilateral policies'); git(root,'update-ref','refs/remotes/origin/main','HEAD')
    sha=git(root,'rev-parse','HEAD')
    old_host=CoordinationBinding(('beta','.'),'refs/remotes/origin/main','wiki.config.yaml')
    old=prepare(root,old_host,context_id='beta',approved_revision=sha,entry_folder='beta',entry_index='beta/index.md',source_ref='source.txt',source_context='same',artifact_context='.')
    old_path=next((root/'data/derived/wiki/.wiki-viva-protected').rglob('*'+old['request_id']+'-llm-context-request.json'))
    current_host=CoordinationBinding(('alpha','.'),'refs/remotes/origin/main','wiki.config.yaml')
    pending=prepare(root,current_host,context_id='alpha',approved_revision=sha,entry_folder='alpha',entry_index='alpha/index.md',source_ref='source.txt',source_context='same',artifact_context='.')
    selected=[pending['request']['chunks'][0]['chunk_id']]
    opened=[]; original=Path.open
    def spy(path,*a,**kw):
        if path==old_path: opened.append(path)
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'open',spy)
    current=prepare(root,current_host,context_id='alpha',approved_revision=sha,entry_folder='alpha',entry_index='alpha/index.md',source_ref='source.txt',source_context='same',artifact_context='.',previous_request_id=old['request_id'],candidate_chunk_ids=selected)
    assert old['source_id']==current['source_id']
    assert current['historical_review']['status']=='unavailable'
    assert not opened, 'historical request from another executor was opened'
    print('CROSS_EXECUTOR_REQUEST_NOT_OPENED', flush=True)


def test_context_boundary_change_blocks_next_historical_body(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    (root / 'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system'); rows = before['request']['chunks'][:2]
    assert len(rows) == 2
    sample = _result_for(before['request'])
    results = [{**sample, **{key: row[key] for key in ('cache_key', 'chunk_id', 'context_sha256', 'chunk_hash_sha256')}} for row in rows]
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=results)
    binding = grant_prior(binding, args, before, sha); new_sha = advance(root)
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    selected = [row['chunk_id'] for row in pending['request']['chunks'][:2]]
    original = protected._read_json; changed = []; unsafe = []
    def mutate(*a, **kw):
        path = a[3]
        if path.name == rows[1]['cache_key'] + '.json' and changed: unsafe.append(path)
        value = original(*a, **kw)
        if path.name == rows[0]['cache_key'] + '.json' and not changed:
            index = root / 'index.md'; moved = root / 'index-moved.md'
            index.rename(moved); index.symlink_to(moved); changed.append(True)
        return value
    monkeypatch.setattr(protected, '_read_json', mutate)
    with pytest.raises(protected.ProtectedPartialError):
        prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
            previous_request_id=before['request_id'], candidate_chunk_ids=selected)
    assert changed and unsafe == []


@pytest.mark.parametrize('missing', ['request', 'result', 'tampered_request'])
def test_unavailable_historical_evidence_does_not_block_current_request(prepared_repo, monkeypatch, missing):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system'); result = _result_for(before['request'])
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    binding = grant_prior(binding, args, before, sha)
    directory = root / 'data/derived/wiki/.wiki-viva-protected'
    previous_path = next(directory.rglob('*' + before['request_id'] + '-llm-context-request.json'))
    result_path = directory / 'llm-cache' / (result['cache_key'] + '.json')
    if missing == 'request': previous_path.unlink()
    elif missing == 'result': result_path.unlink()
    else: previous_path.write_text('{broken')
    new_sha = advance(root)
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    original = Path.open
    def sentinel(path, *a, **kw):
        if missing in ('request', 'tampered_request') and path == result_path:
            pytest.fail('old result opened without a valid prior request')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    current = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
        previous_request_id=before['request_id'], candidate_chunk_ids=[pending['request']['chunks'][0]['chunk_id']])
    assert current['historical_review']['status'] == 'unavailable'
    assert current['request']['chunks'][0]['result_exists'] is False


def test_trusted_local_cli_requires_host_grant_for_historical_review(prepared_repo):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'],
           results=[_result_for(before['request'])])
    new_sha = advance(root)
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    env = {key: value for key, value in os.environ.items() if not key.startswith('WIKI_COORDINATION_')}
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_coordination.py'
    payload = {'entry_folder': '.', 'entry_index': 'index.md', 'source_ref': 'source.txt',
               'source_context': 'system', 'context_selection': {'omit_root_entity': True},
               'previous_request_id': before['request_id'], 'candidate_chunk_ids': [pending['request']['chunks'][0]['chunk_id']]}
    def call(environment):
        completed = subprocess.run([sys.executable, str(script), '--root', str(root), '--context-id', '.',
            '--approved-revision', new_sha, '--source-stage', 'prepare'], input=json.dumps(payload), text=True,
            capture_output=True, check=True, env=environment)
        return json.loads(completed.stdout)['result']
    no_grant = call(env)
    assert no_grant['historical_review']['status'] == 'unavailable'
    grant = {'executor': '.', 'integrator': '.', 'source_ref': 'source.txt', 'source_id': before['source_id'],
             'request_id': before['request_id'], 'policy_revision': sha}
    env.update(WIKI_COORDINATION_ALLOWED_CONTEXTS='.',
               WIKI_COORDINATION_PREVIOUS_REQUEST_GRANTS=json.dumps([grant]))
    result = call(env)
    assert result['historical_review']['status'] == 'review_needed'
    assert result['historical_review']['candidates'][0]['origin']['policy_revision'] == sha
    assert result['request']['chunks'][0]['result_exists'] is False


def test_candidate_over_budget_returns_no_historical_body(prepared_repo, monkeypatch):
    from wiki_core.ingest import protected
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'],
           results=[_result_for(before['request'])])
    binding = grant_prior(binding, args, before, sha); new_sha = advance(root)
    pending = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system')
    original = protected.canonical_request_text
    def synthetic_size(value):
        if isinstance(value, dict) and value.get('status') == 'review_needed' and 'result' in value:
            return ' ' * 2_000_001
        return original(value)
    monkeypatch.setattr(protected, 'canonical_request_text', synthetic_size)
    outcome = prepare(root, binding, **{**args, 'approved_revision': new_sha}, source_context='system',
        previous_request_id=before['request_id'], candidate_chunk_ids=[pending['request']['chunks'][0]['chunk_id']])
    assert outcome['historical_review']['status'] == 'unavailable'
    assert outcome['historical_review']['reason'] == 'candidate_response_budget_exceeded'
    assert 'candidates' not in outcome['historical_review']
    assert outcome['request']['chunks'][0]['result_exists'] is False


def test_stale_candidate_chunk_id_does_not_block_current_request(prepared_repo, monkeypatch):
    root, sha = prepared_repo
    binding = CoordinationBinding(('.',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    args = dict(context_id='.', approved_revision=sha, entry_folder='.', entry_index='index.md', source_ref='source.txt')
    before = prepare(root, binding, **args, source_context='system')
    result = _result_for(before['request'])
    record(root, binding, **args, source_id=before['source_id'], request_id=before['request_id'], results=[result])
    binding = grant_prior(binding, args, before, sha)
    previous_path = next((root / 'data/derived/wiki/.wiki-viva-protected').rglob('*' + before['request_id'] + '-llm-context-request.json'))
    write(root, 'source.txt', 'Different source and chunk identity.\n')
    original = Path.open
    def sentinel(path, *a, **kw):
        if path == previous_path: pytest.fail('old request opened for a stale candidate selection')
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, 'open', sentinel)
    outcome = prepare(root, binding, **args, source_context='system', previous_request_id=before['request_id'],
                      candidate_chunk_ids=[before['request']['chunks'][0]['chunk_id']])
    assert outcome['source_id'] != before['source_id']
    assert outcome['historical_review']['status'] == 'unavailable'
    assert outcome['historical_review']['reason'] == 'candidate_selection_changed'
    assert outcome['request']['pending_llm_calls'] > 0


def test_late_historical_change_does_not_block_current_request(prepared_repo,monkeypatch):
    import wiki_core.ingest.protected as p
    root,sha=prepared_repo
    binding=CoordinationBinding(('.',),'refs/remotes/origin/main','wiki.config.yaml')
    args=dict(context_id='.',approved_revision=sha,entry_folder='.',entry_index='index.md',source_ref='source.txt')
    old=prepare(root,binding,**args,source_context='system');result=_result_for(old['request'])
    record(root,binding,**args,source_id=old['source_id'],request_id=old['request_id'],results=[result])
    grant=PreviousRequestGrant('.','.','source.txt',old['source_id'],old['request_id'],sha)
    binding=replace(binding,previous_request_grants=(grant,))
    write(root,'beta/unrelated.md','# unrelated\n');git(root,'add','beta/unrelated.md');git(root,'commit','-qm','unrelated');git(root,'update-ref','refs/remotes/origin/main','HEAD');new_sha=git(root,'rev-parse','HEAD')
    new_args={**args,'approved_revision':new_sha};current=prepare(root,binding,**new_args,source_context='system');row=current['request']['chunks'][0]
    old_file=root/'data/derived/wiki/.wiki-viva-protected/llm-cache'/(result['cache_key']+'.json')
    original=p._read_json; changed=[]
    def mutate(*a,**kw):
        if a[3].name==row['cache_key']+'.json' and not changed:
            old_file.write_text(json.dumps({**result,'synthetic_note':'changed'}));changed.append(True)
        return original(*a,**kw)
    monkeypatch.setattr(p,'_read_json',mutate)
    out=prepare(root,binding,**new_args,source_context='system',previous_request_id=old['request_id'],candidate_chunk_ids=[row['chunk_id']])
    assert changed and out['historical_review']['status']=='unavailable'
    assert out['request_id']==current['request_id'] and out['request']['chunks'][0]['result_exists'] is False


def test_source_change_blocks_later_historical_body(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as p
    root,sha=prepared_repo
    (root/'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding=CoordinationBinding(('.',),'refs/remotes/origin/main','wiki.config.yaml')
    args=dict(context_id='.',approved_revision=sha,entry_folder='.',entry_index='index.md',source_ref='source.txt')
    old=prepare(root,binding,**args,source_context='system');rows=old['request']['chunks'];assert len(rows)>=2
    sample=_result_for(old['request']); results=[{**sample,**{k:r[k] for k in ('cache_key','chunk_id','context_sha256','chunk_hash_sha256')}} for r in rows]
    record(root,binding,**args,source_id=old['source_id'],request_id=old['request_id'],results=results)
    grant=PreviousRequestGrant('.','.','source.txt',old['source_id'],old['request_id'],sha);binding=replace(binding,previous_request_grants=(grant,))
    write(root,'beta/unrelated.md','# unrelated\n');git(root,'add','beta/unrelated.md');git(root,'commit','-qm','unrelated');git(root,'update-ref','refs/remotes/origin/main','HEAD');new_sha=git(root,'rev-parse','HEAD')
    new_args={**args,'approved_revision':new_sha};pending=prepare(root,binding,**new_args,source_context='system'); ids=[r['chunk_id'] for r in pending['request']['chunks'][:2]]
    original=p._read_json;changed=[];later=[]; old0=rows[0]['cache_key']+'.json';old1=rows[1]['cache_key']+'.json'
    def mutate(*a,**kw):
        if a[3].name==old1 and changed: later.append(True)
        value=original(*a,**kw)
        if a[3].name==old0 and not changed:
            with (root/'source.txt').open('a') as f: f.write(' changed')
            changed.append(True)
        return value
    monkeypatch.setattr(p,'_read_json',mutate)
    try:
        prepare(root,binding,**new_args,source_context='system',previous_request_id=old['request_id'],candidate_chunk_ids=ids)
    except ValueError:
        pass
    assert changed and not later, f'{changed=} {later=}'


def test_request_change_blocks_later_historical_body(prepared_repo, monkeypatch):
    import wiki_core.ingest.protected as p
    root,sha=prepared_repo
    (root/'source.txt').write_text(''.join(f'Synthetic evidence {i} with bounded detail.\n' for i in range(500)))
    binding=CoordinationBinding(('.',),'refs/remotes/origin/main','wiki.config.yaml')
    args=dict(context_id='.',approved_revision=sha,entry_folder='.',entry_index='index.md',source_ref='source.txt')
    old=prepare(root,binding,**args,source_context='system');rows=old['request']['chunks'];assert len(rows)>=2
    sample=_result_for(old['request']); results=[{**sample,**{k:r[k] for k in ('cache_key','chunk_id','context_sha256','chunk_hash_sha256')}} for r in rows]
    record(root,binding,**args,source_id=old['source_id'],request_id=old['request_id'],results=results)
    grant=PreviousRequestGrant('.','.','source.txt',old['source_id'],old['request_id'],sha);binding=replace(binding,previous_request_grants=(grant,))
    write(root,'beta/unrelated.md','# unrelated\n');git(root,'add','beta/unrelated.md');git(root,'commit','-qm','unrelated');git(root,'update-ref','refs/remotes/origin/main','HEAD');new_sha=git(root,'rev-parse','HEAD')
    new_args={**args,'approved_revision':new_sha};pending=prepare(root,binding,**new_args,source_context='system'); ids=[r['chunk_id'] for r in pending['request']['chunks'][:2]]
    original=p._read_json;changed=[];later=[]; old0=rows[0]['cache_key']+'.json';old1=rows[1]['cache_key']+'.json'
    def mutate(*a,**kw):
        if a[3].name==old1 and changed: later.append(True)
        value=original(*a,**kw)
        if a[3].name==old0 and not changed:
            current_request=next((root/'data/derived/wiki/.wiki-viva-protected').rglob('*'+pending['request_id']+'-llm-context-request.json'))
            with current_request.open('a') as f: f.write(' ')
            changed.append(True)
        return value
    monkeypatch.setattr(p,'_read_json',mutate)
    try:
        prepare(root,binding,**new_args,source_context='system',previous_request_id=old['request_id'],candidate_chunk_ids=ids)
    except ValueError:
        pass
    assert changed and not later, f'{changed=} {later=}'
