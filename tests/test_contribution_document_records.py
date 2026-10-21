"""Real public kit gates for a contribution under an exact record contract.

Only synthetic local Git/CLI data; no provider, model, account or GitHub call.
"""
from __future__ import annotations

import datetime as dt
import os
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
import pytest

from wiki_core.config import load_config
from wiki_core.document_records import digest, edge_digest, sections
from wiki_core.freshness_impact import authored_graph
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.web.git_workflows import run_git_workflow
from test_action_contribution import review, fixture
import wiki_core.action_contribution as port
from wiki_core.contribution_records import support_path


SOURCE = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()


def command(root, *args):
    result = subprocess.run(args, cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, (args, result.stdout[-5000:], result.stderr[-2000:])
    return result.stdout


def fullmap_consumer(tmp_path, *, support=False, guarded=False):
    root = tmp_path / 'consumer'
    command(tmp_path, 'git', 'clone', '--shared', '--quiet', str(SOURCE), str(root))
    git(root, 'switch', '-C', 'main')
    git(root, 'remote', 'remove', 'origin')
    git(root, 'config', 'user.name', 'Synthetic Contract Operator')
    git(root, 'config', 'user.email', 'contract@example.invalid')
    # Exercise actual working product code during local development as well as
    # committed CI. These are public sources, not executable gate stubs.
    for directory in ('scripts', 'wiki_core'):
        shutil.copytree(SOURCE / directory, root / directory, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    config_file = root / 'wiki.config.yaml'
    config = yaml.safe_load(config_file.read_text())
    config['repo_id'] = 'synthetic-contract-consumer'
    if support:
        config.setdefault('approval', {})['contribution_record_support'] = True
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    # The canonical body writer stamps UTC, independently of the host timezone.
    # A prior-day action really changes the pass view and must require C3.
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for path in (root / 'memories').rglob('*.md'):
        text = path.read_text()
        match = FRONTMATTER_RE.match(text)
        if match:
            # Initial fictional test state, not renewal of any private page.
            front = re.sub(r'(?m)^updated_at:.*$', 'updated_at: ' + today, match.group(0))
            path.write_text(front + text[match.end():])
    action = root / 'memories/actions/contract-example.md'
    action.parent.mkdir(exist_ok=True)
    values = dict(page_id='action-contract-example', page_type='action', title='Synthetic contract action',
                  context='example', visibility='private_self', updated_at=today, stale_after_days=30,
                  sources_policy='synthetic_only', gate='github_pr', sensitive_data_policy='private_sensitive_allowed',
                  actions=[], claims=[], decisions=[], evidence_refs=[], owner=[], related_holons=[],
                  responsibilities=[], roles=[], source_refs=['sources-wiki-viva-methodology'],
                  moc_parent='memories/example/index.md', action_state='open', owner_kind='unassigned',
                  created_at=today, next_action='Review fictional source.', priority='normal',
                  attention_basis='Synthetic exact-contract lifecycle only.')
    action.write_text('---\n' + yaml.safe_dump(values, sort_keys=False) + '---\n\n# Synthetic contract action\n\n'
                      'Fictional evidence for the [example context](../example/index.md).\n')
    if guarded:
        action.write_text(action.read_text() + 'Record this result in [the log](../system/log.md).\n')
    hub = root / 'memories/example/index.md'
    hub.write_text(hub.read_text() + '\n- [Synthetic contract action](../actions/contract-example.md).\n')
    log = root / 'memories/system/log.md'
    log.write_text(log.read_text() + '\n## Preserved final note\n\nAn existing fictional historical unit.\n')
    for script in ('wiki_source_registry', 'wiki_input_stage', 'wiki_operation_compile', 'wiki_operational_pass'):
        command(root, sys.executable, 'scripts/' + script + '.py', '--write')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Initial complete public fictional consumer')
    base = git(root, 'rev-parse', 'HEAD')
    graph = authored_graph(root, load_config(root))
    assert not graph['errors']
    heading = 'Preserved final note'
    log_sha = digest(sections(graph['documents']['memories/system/log.md'])[1][heading][2])
    contract = dict(schema_version='document_record.v1',
                    **{o + '_documents_sha256': {p: digest(t) for p, t in graph['documents'].items()}
                       for o in ('base', 'current')},
                    documents=[dict(path='memories/system/log.md', records=[dict(
                        id='preserved-note', heading=heading, base_sha256=log_sha, current_sha256=log_sha,
                        independent=True, rationale='Existing historical note with no current-state claim.',
                        epistemic_status='observation', recorded_on=today, context_records=[])])], bindings=[])
    if guarded:
        edge, = [e for e in graph['edges'] if e.get('source') == 'memories/actions/contract-example.md'
                 and e.get('target') == 'memories/system/log.md']
        artifact = root / 'docs/synthetic-log-capture.txt'
        artifact.write_text('Observed the log before this contribution. This capture has no future scope.\n')
        contract['artifacts'] = [dict(origin='current', id='old-log-observation',
                                     path='docs/synthetic-log-capture.txt', sha256=digest(artifact.read_text()))]
        contract['bindings'] = [dict(origin='current', edge_sha256=edge_digest(edge),
                                    role='change_target', consumer_record='document',
                                    prerequisite_document_sha256=digest(graph['documents']['memories/system/log.md']),
                                    evidence=['old-log-observation'],
                                    rationale='This capture proves this specific prior log update only.')]
    records = root / 'docs/contribution-records.json'
    records.write_text(json.dumps(contract, indent=2) + '\n')
    config = yaml.safe_load(config_file.read_text())
    config.setdefault('audit', {}).update(freshness_scope='impact', freshness_base=base,
                                         freshness_records='docs/contribution-records.json')
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Bind complete exact documentary contract')
    # Prove a healthy actual baseline before the contribution introduces drift.
    command(root, sys.executable, 'scripts/wiki_audit.py', '--check')
    for script in ('wiki_source_registry', 'wiki_input_stage', 'wiki_operation_compile', 'wiki_operational_pass'):
        command(root, sys.executable, 'scripts/' + script + '.py', '--check')
    before = action.read_text()
    proposed = before.replace('Fictional evidence', 'Reviewed fictional evidence')
    request = dict(schema_version='wiki_action_contribution.v1',
                   task_ref=dict(repo_id='synthetic-contract-consumer', action_id='action-contract-example'),
                   run_ref=dict(runtime='local-synthetic', task_id='fixture-task', run_id='one'),
                   session_ref=dict(session_id='fixture-author', coverage='Synthetic source only; no model/provider'),
                   effect_key='synthetic-contract-body-one', files=[dict(
                       path=action.relative_to(root).as_posix(), base_commit=git(root, 'rev-parse', 'HEAD'),
                       base_sha256=digest(before), sha256=digest(proposed), text=proposed)])
    return root, action, log, records, request


def test_canonical_prepare_refuses_full_snapshot_contract_without_support(tmp_path):
    root, action, log, records, request = fullmap_consumer(tmp_path)
    before = {p: p.read_bytes() for p in (action, log, records)}
    head = git(root, 'rev-parse', 'HEAD')
    refs = git(root, 'for-each-ref', '--format=%(refname) %(objectname)')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    print(json.dumps(result, sort_keys=True))
    assert not result['ok'] and result['error'].startswith('proposal_gate_failed:')
    assert result['gate_receipts'][0]['exit_code'] != 0
    assert 'current: document snapshot does not match record contract' in result['gate_receipts'][0]['diagnostic_tail']
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'rev-parse', 'HEAD') == head
    assert not git(root, 'branch', '--list', result['branch'])
    assert git(root, 'for-each-ref', '--format=%(refname) %(objectname)') == refs


def test_opt_in_prepares_exact_support_with_real_producers_and_reuses(tmp_path, monkeypatch):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True)
    before = {p: p.read_bytes() for p in (action, log, records)}
    head = git(root, 'rev-parse', 'HEAD')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    print(json.dumps(result, sort_keys=True))
    assert result['ok'] and result['status'] == 'prepared', result
    assert len(result['gate_receipts']) == 7
    assert all(gate['exit_code'] == 0 for gate in result['gate_receipts'])
    commit = result['proposal_commit']
    changed = git(root, 'diff', '--name-only', head, commit).splitlines()
    assert changed == sorted(p.relative_to(root).as_posix() for p in before)
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'rev-parse', 'HEAD') == head
    old = json.loads(before[records])
    generated = json.loads(git(root, 'show', commit + ':' + records.relative_to(root).as_posix()))
    assert generated['base_documents_sha256'] == old['base_documents_sha256']
    assert {p for p in old['current_documents_sha256'] if old['current_documents_sha256'][p]
            != generated['current_documents_sha256'][p]} == {action.relative_to(root).as_posix(), log.relative_to(root).as_posix()}
    assert generated['documents'][0]['records'][0]['base_sha256'] == old['documents'][0]['records'][0]['base_sha256']
    assert generated['documents'][0]['records'][0]['current_sha256'] != old['documents'][0]['records'][0]['current_sha256']
    again = run_git_workflow(root, load_config(root), 'prepare_contribution',
                            {'request': request, 'review': review(request)}, dry_run=False)
    assert again['ok'] and again['idempotent'] and again['proposal_commit'] == commit, again
    # Forge only this test proposal's metadata blob, without changing source.
    environment = {**os.environ, 'GIT_INDEX_FILE': str(tmp_path / 'tamper-index')}
    def indexed(*args, data=None):
        process = subprocess.run(['git', *args], cwd=root, env=environment,
                                 input=data, text=True, capture_output=True, check=True)
        return process.stdout.strip()
    indexed('read-tree', commit)
    blob = indexed('hash-object', '-w', '--stdin', data=json.dumps({**generated, 'forged': True}) + '\n')
    indexed('update-index', '--cacheinfo', '100644,' + blob + ',' + records.relative_to(root).as_posix())
    forged = indexed('commit-tree', indexed('write-tree'), '-p', head, '-m', 'Synthetic support tamper')
    git(root, 'update-ref', 'refs/heads/' + result['branch'], forged, commit)
    tamper = run_git_workflow(root, load_config(root), 'prepare_contribution',
                             {'request': request, 'review': review(request)}, dry_run=False)
    assert tamper['error'] == 'candidate_record_support_tampered', tamper
    assert {p: p.read_bytes() for p in before} == before
    git(root, 'update-ref', 'refs/heads/' + result['branch'], commit, forged)
    # Simulated GitHub metadata, actual local Git merge/readback of every blob.
    bare = tmp_path / 'origin.git'
    git(tmp_path, 'init', '--bare', str(bare))
    git(root, 'remote', 'add', 'origin', str(bare))
    git(root, 'push', '-q', 'origin', 'main', result['branch'])
    merged = dict(number=7, state='OPEN', headRefOid=commit, headRefName=result['branch'],
                  baseRefName='main', isCrossRepository=False,
                  headRepository={'name': 'wiki'}, headRepositoryOwner={'login': 'synthetic'})
    monkeypatch.setattr(port, '_repository', lambda *_: 'github.com/synthetic/wiki')
    monkeypatch.setattr(port, '_pr', lambda *_: dict(merged))
    # A real canonical advance must refuse even when the action/log are intact.
    git(root, 'commit', '--allow-empty', '-qm', 'Synthetic intervening main commit')
    git(root, 'push', '-q', 'origin', 'main')
    refused = run_git_workflow(root, load_config(root), 'publish_contribution', {'request': request}, dry_run=False)
    assert refused['error'] == 'record_support_canonical_parent_advanced: reconcile required', refused
    git(root, 'reset', '--hard', head)
    git(root, 'push', '-q', '--force', 'origin', 'main')
    git(root, 'merge', '--no-ff', '--no-edit', commit)
    merge = git(root, 'rev-parse', 'HEAD')
    git(root, 'push', '-q', 'origin', 'main')
    merged.update(state='MERGED', mergeCommit={'oid': merge})
    # Lost local proposal ref: reconciliation uses the retained remote ref,
    # verifies the exact 3-file tree and never calls an external effect.
    git(root, 'update-ref', '-d', 'refs/heads/' + result['branch'], commit)
    observed = run_git_workflow(root, load_config(root), 'reconcile_contribution',
                               {'request': request, 'pr': 7}, dry_run=False)
    assert observed['ok'] and observed['remote_merged'] and observed['canonical_body_adopted'], observed
    assert len(observed['readback_files']) == 3
    assert not git(root, 'branch', '--list', result['branch'])
    # Recovery validates immutable Git even when the selected checkout still
    # needs adoption. Never follow a local alias or claim a wrong mode adopted.
    support_bytes = records.read_bytes()
    alias_target = tmp_path / 'same-bytes-outside-checkout.json'
    alias_target.write_bytes(support_bytes)
    recoveries = []
    for mutation in ('missing', 'symlink', 'executable'):
        try:
            if mutation == 'executable':
                records.chmod(0o755)
            else:
                records.unlink()
                if mutation == 'symlink':
                    records.symlink_to(alias_target)
            recovery = run_git_workflow(root, load_config(root), 'reconcile_contribution',
                                       {'request': request, 'pr': 7}, dry_run=False)
            recoveries.append((mutation, recovery))
            assert not git(root, 'branch', '--list', result['branch'])
            assert alias_target.read_bytes() == support_bytes
        finally:
            if records.is_symlink():
                records.unlink()
            records.write_bytes(support_bytes)
            records.chmod(0o644)
    assert all(value.get('ok') and value.get('remote_merged')
               and value.get('status') == 'waiting_worktree_adoption'
               and value.get('worktree_adopted') is False
               for _, value in recoveries), recoveries
    # Later memory drift with unchanged support is not a valid full snapshot.
    unrelated = root / 'memories/example/index.md'
    unrelated.write_text(unrelated.read_text() + '\nUnrelated synthetic new claim.\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Synthetic later document drift')
    git(root, 'push', '-q', 'origin', 'main')
    drift = run_git_workflow(root, load_config(root), 'reconcile_contribution',
                            {'request': request, 'pr': 7}, dry_run=False)
    assert not drift['ok'] and drift['remote_merged'] and not drift['canonical_body_adopted'], drift
    assert drift['status'] == 'unknown'


@pytest.mark.parametrize('mutation', ['support', 'producer'])
def test_opt_in_does_not_discard_support_wip_or_regenerate_views(tmp_path, mutation):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True)
    if mutation == 'support':
        records.write_text(records.read_text() + '\n')
    else:
        request['files'][0]['text'] = request['files'][0]['text'].replace('# Synthetic contract action', '# Changed producer title')
        request['files'][0]['sha256'] = digest(request['files'][0]['text'])
    before = {p: p.read_bytes() for p in (action, log, records)}
    refs = git(root, 'for-each-ref', '--format=%(refname) %(objectname)')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    assert not result['ok'], result
    if mutation == 'support':
        assert result['error'] == 'uncommitted_record_support'
    else:
        assert result['error'].startswith('proposal_gate_failed:'), result
        assert result['gate_receipts'][-1]['exit_code'] != 0
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'for-each-ref', '--format=%(refname) %(objectname)') == refs


def test_temporal_change_target_evidence_requires_explicit_c3(tmp_path):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True, guarded=True)
    before = {p: p.read_bytes() for p in (action, log, records)}
    refs = git(root, 'for-each-ref', '--format=%(refname) %(objectname)')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    assert not result['ok'] and result['error'].startswith('record_support_c3_required:binding/'), result
    assert '/prerequisite_document_sha256/evidence/rationale' in result['error']
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'for-each-ref', '--format=%(refname) %(objectname)') == refs


@pytest.mark.parametrize('case', ['alias', 'memory', 'raw', 'executable', 'symlink', 'flag_string'])
def test_operator_support_path_is_not_an_arbitrary_third_file(tmp_path, case):
    # Path/ownership unit checks only; this fixture's gate stubs are never run.
    fixture(tmp_path)
    config_path = tmp_path / 'wiki.config.yaml'
    config = yaml.safe_load(config_path.read_text())
    config.setdefault('approval', {})['contribution_record_support'] = 'true' if case == 'flag_string' else True
    ref = {'alias': 'docs/../records.json', 'memory': 'memories/records.json',
           'raw': 'data/raw/records.json'}.get(case, 'docs/records.json')
    config.setdefault('audit', {})['freshness_records'] = ref
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    record = tmp_path / ref
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text('{}\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'Synthetic support ownership policy')
    parent = git(tmp_path, 'rev-parse', 'HEAD')
    if case == 'executable':
        record.chmod(0o755)
    elif case == 'symlink':
        other = tmp_path / 'other.json'
        other.write_bytes(record.read_bytes())
        record.unlink()
        record.symlink_to(other)
    with pytest.raises(ValueError, match='record_support'):
        support_path(tmp_path, parent)
