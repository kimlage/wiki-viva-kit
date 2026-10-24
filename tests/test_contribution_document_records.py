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
from wiki_core.document_records import artifact_paths, digest, edge_digest, project_records, sections
from wiki_core.freshness_impact import authored_graph
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.markdown_link_roles import declare_link_role
from wiki_core.web.git_workflows import run_git_workflow
from test_action_contribution import review, fixture
import wiki_core.action_contribution as port
from wiki_core.contribution_records import support_path
from scripts.wiki_page_graph import project_memory_at_commit


SOURCE = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()


def command(root, *args):
    result = subprocess.run(args, cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, (args, result.stdout[-5000:], result.stderr[-2000:])
    return result.stdout


def fullmap_consumer(tmp_path, *, support=False, guarded=False, captured=False, effects=False,
                     effect_consumer=False, prior_day=False, historical_consumer=False,
                     unselected_tail=False, changed_consumer=False, inherited_event=False,
                     qualified_context=False):
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
    action_day = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=int(prior_day))).isoformat()
    values = dict(page_id='action-contract-example', page_type='action', title='Synthetic contract action',
                  context='example', visibility='private_self', updated_at=action_day, stale_after_days=30,
                  sources_policy='synthetic_only', gate='github_pr', sensitive_data_policy='private_sensitive_allowed',
                  actions=[], claims=[], decisions=[], evidence_refs=[], owner=[], related_holons=[],
                  responsibilities=[], roles=[], source_refs=['sources-wiki-viva-methodology'],
                  moc_parent='memories/example/index.md', action_state='open', owner_kind='unassigned',
                  created_at=action_day, next_action='Review fictional source.', priority='normal',
                  attention_basis='Synthetic exact-contract lifecycle only.')
    if effects:
        values['action_state_history'] = []  # Healthy schema and a first canonical body receipt.
    action.write_text('---\n' + yaml.safe_dump(values, sort_keys=False) + '---\n\n# Synthetic contract action\n\n'
                      'Fictional evidence for the [example context](../example/index.md).\n')
    if guarded:
        action.write_text(action.read_text() + 'Record this result in [the log](../system/log.md).\n')
    if effect_consumer:
        action.write_text(action.read_text().replace('# Synthetic contract action\n',
            '# Synthetic contract action\n\nRecord this update in [the log](../system/log.md).\n'))
    if historical_consumer:
        consumer = action if changed_consumer else root / 'memories/index.md'
        target = '../system/log.md' if changed_consumer else 'system/log.md'
        consumer.write_text(consumer.read_text() + '\n## Original fictional history\n\n'
                            'The initial fictional history remains in [the preserved log]('
                            + target + ').\n')
    hub = root / 'memories/example/index.md'
    hub.write_text(hub.read_text() + '\n- [Synthetic contract action](../actions/contract-example.md).\n')
    if effects:
        hub.write_text(hub.read_text() + '\nRecord the actual update in [the log](../system/log.md).\n'
                       '\nBefore completing the change, annotate [the log](../system/log.md).\n')
    log = root / 'memories/system/log.md'
    log.write_text(log.read_text() + '\n## Preserved final note\n\nAn existing fictional historical unit.\n')
    if unselected_tail:
        log.write_text(log.read_text() + '\n## Other preserved note\n\nAnother original fictional unit.\n')
    if inherited_event:
        event = root / 'memories/system/ingestion/events/retained-history-example.md'
        # A separate fictional event/source keeps the declared occurrence clear.
        # Minimal freshness fixtures cover stale debt; this full-kit fixture
        # keeps other unqualified whole-document consumers operationally valid.
        source = root / 'memories/sources/retained-history-example.md'
        source_values = dict(page_id='source-retained-fictional-history', page_type='source',
            title='Retained fictional source', context='system', visibility='private_self',
            updated_at=today, stale_after_days=90, sources_policy='synthetic_only',
            gate='github_pr', sensitive_data_policy='private_sensitive_allowed',
            source_type='reference', refresh_policy='archival', source_refs=[],
            actions=[], claims=[], decisions=[], evidence_refs=[], owner=[], related_holons=[],
            responsibilities=[], roles=[],
            moc_parent='memories/index.md')
        source.write_text('---\n' + yaml.safe_dump(source_values, sort_keys=False) + '---\n\n'
                          '# Retained fictional source\n\nA self-contained fictional history.\n')
        event_values = dict(page_id='event-retained-fictional-history', page_type='ingestion_event',
            event_id='retained-fictional-history', context='system', visibility='private_self',
            updated_at=today, stale_after_days=90, sources_policy='retained_synthetic_observation',
            gate='github_pr', sensitive_data_policy='private_sensitive_allowed',
            source_refs=['source-retained-fictional-history'],
            consolidated_into=['memories/system/log.md'], moc_parent='memories/system/ingestion/events/README.md')
        event.write_text('---\n' + yaml.safe_dump(event_values, sort_keys=False) + '---\n\n'
            '# Retained fictional history\n\n## Source\n\nA retained fictional observation.\n\n'
            '## Quadrants\n\n| Quadrant | Observation |\n| --- | --- |\n'
            '| Interior individual | No personal statement in this fixture. |\n'
            '| Exterior individual | A historical event named its write destination. |\n'
            '| Interior collective | No collective statement in this fixture. |\n'
            '| Exterior collective | The exact destination relation remains archived. |\n')
        for label, target in [('Historical event', '../system/ingestion/events/retained-history-example.md'),
                              ('Historical source', '../sources/retained-history-example.md')]:
            hub.write_text(hub.read_text() + '\n' + declare_link_role(f'[{label}]({target})', 'navigation') + '\n')
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
    if captured:
        artifact = root / 'docs/synthetic-frozen-capture.json'
        artifact.write_text('{"scope": "Synthetic frozen observation, no live permissions"}\n')
        contract['artifacts'] = [dict(origin='current', id='synthetic-frozen-observation',
                                     path='docs/synthetic-frozen-capture.json', sha256=digest(artifact.read_text()))]
    if guarded or effects:
        edges = [e for e in graph['edges'] if e.get('source') ==
                 ('memories/example/index.md' if effects else 'memories/actions/contract-example.md')
                 and e.get('target') == 'memories/system/log.md']
        assert len(edges) == (2 if effects else 1)
        edge = edges[0]
        artifact = root / 'docs/synthetic-log-capture.txt'
        artifact.write_text('Observed the log before this contribution. This capture has no future scope.\n')
        contract['artifacts'] = [dict(origin='current', id='old-log-observation',
                                     path='docs/synthetic-log-capture.txt', sha256=digest(artifact.read_text()))]
        contract['bindings'] = [dict(origin='current', edge_sha256=edge_digest(edge),
                                    role='change_target', consumer_record='document',
                                    prerequisite_document_sha256=digest(graph['documents']['memories/system/log.md']),
                                    evidence=['old-log-observation'],
                                    rationale='This capture proves this specific prior log update only.')]
    if effects:
        # Explicit synthetic parent authorship, never an automatic conversion
        # of an evidence-bearing guard by the contribution helper.
        contract['schema_version'] = 'document_record.v2'
        contract['document_modes'] = {'memories/system/log.md': 'h2_v1'}
        contract['artifacts'].append(dict(origin='current', id='synthetic-frozen-observation',
            path='docs/synthetic-frozen-capture.json',
            sha256=digest((root / 'docs/synthetic-frozen-capture.json').read_text())))
        note = contract['documents'][0]['records'][0]
        note['current_evidence'] = ['old-log-observation']
        note['rationale'] += ' The old capture proves this past note only, never the next update.'
        for binding in contract['bindings']:
            binding.pop('evidence')
            binding['contribution_effect'] = 'canonical_log_annotation'
            binding['rationale'] = 'This occurrence requires the actual new canonical annotation; past proof stays on the historical record.'
        edge = edges[1]
        contract['bindings'].append(dict(origin='current', edge_sha256=edge_digest(edge),
            consumer_record='document', role='change_target',
            contribution_effect='canonical_log_annotation',
            prerequisite_document_sha256=digest(graph['documents']['memories/system/log.md']),
            rationale='A second independently authored exact obligation; not all historical log facts.'))
    if effect_consumer:
        edge, = [e for e in graph['edges'] if e.get('source') == 'memories/actions/contract-example.md'
                 and e.get('target') == 'memories/system/log.md']
        contract['bindings'].append(dict(origin='current', edge_sha256=edge_digest(edge),
            consumer_record='document', role='change_target',
            contribution_effect='canonical_log_annotation',
            prerequisite_document_sha256=digest(graph['documents']['memories/system/log.md']),
            rationale='Parent qualification cannot survive a changed consumer context.'))
    if inherited_event:
        edge, = [e for e in graph['edges'] if e.get('path') == event.relative_to(root).as_posix()
                 and e.get('field') == 'consolidated_into' and e.get('target') == 'memories/system/log.md']
        binding = dict(origin='current', edge_sha256=edge_digest(edge), consumer_record='preserved-note',
            role='change_target', prerequisite_document_sha256=digest(event.read_text()),
            rationale='This event names a historical write destination; it did not supply the later preserved note.')
        contract['bindings'].append(binding)
        contract['bindings'].append({**binding, 'origin': 'base'})
        if qualified_context:
            contract['canonical_log_annotation_context'] = dict(log_path='memories/system/log.md',
                bindings=[dict(edge_sha256=binding['edge_sha256'], consumer_record='preserved-note',
                    rationale='This exact historical destination also supplies no facts to a future fixed '
                              'canonical body-preparation annotation authenticated by its own receipt.')])
    if historical_consumer:
        consumer_ref = consumer.relative_to(root).as_posix()
        edge, = [e for e in graph['edges'] if e.get('source') == consumer_ref
                 and e.get('target') == 'memories/system/log.md'
                 and e.get('section') == 'original fictional history']
        original_log = graph['documents']['memories/system/log.md']
        log_body, log_sections = sections(original_log)
        start, end, _ = log_sections[heading]
        prior_remainder = original_log[:len(original_log) - len(log_body)] + ''.join(
            line for number, line in enumerate(log_body.splitlines(keepends=True))
            if not start <= number < end)
        for origin in ('base', 'current'):
            contract['bindings'].append(dict(origin=origin, edge_sha256=edge_digest(edge),
                consumer_record='document', role='consumption', target_record='remainder',
                consumed_sha256=digest(prior_remainder),
                rationale='This explicit historical assertion consumes the original fictional '
                          'history and its context, not a future contribution annotation.'))
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


@pytest.mark.parametrize('effects', [False, True])
def test_opt_in_prepares_exact_support_with_real_producers_and_reuses(tmp_path, monkeypatch, effects):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True, captured=True, effects=effects)
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
    if effects:
        assert generated['artifacts'][:-1] == old['artifacts']
        assert generated['artifacts'][-1]['document'] == action.relative_to(root).as_posix()
        assert generated['artifacts'][-1]['field'] == 'action_state_history'
        assert generated['documents'][0]['records'][0]['current_evidence'] == ['old-log-observation']
        assert len(generated['bindings']) == 2
        expected_log_hash = digest(subprocess.check_output(
            ['git', 'show', commit + ':memories/system/log.md'], cwd=root).decode())
        for previous, after in zip(old['bindings'], generated['bindings']):
            assert after['prerequisite_document_sha256'] == expected_log_hash
            assert {k: v for k, v in after.items() if k != 'prerequisite_document_sha256'} == {
                k: v for k, v in previous.items() if k != 'prerequisite_document_sha256'}
    assert generated['base_documents_sha256'] == old['base_documents_sha256']
    assert {p for p in old['current_documents_sha256'] if old['current_documents_sha256'][p]
            != generated['current_documents_sha256'][p]} == {action.relative_to(root).as_posix(), log.relative_to(root).as_posix()}
    assert generated['documents'][0]['records'][0]['base_sha256'] == old['documents'][0]['records'][0]['base_sha256']
    assert generated['documents'][0]['records'][0]['current_sha256'] != old['documents'][0]['records'][0]['current_sha256']
    annotation = generated['documents'][0]['records'][-1]
    assert annotation['id'] == 'contribution-' + port.digest(request)
    assert annotation['base_sha256'] is None
    assert annotation['current_evidence'] == [generated['artifacts'][-1]['id']]
    again = run_git_workflow(root, load_config(root), 'prepare_contribution',
                            {'request': request, 'review': review(request)}, dry_run=False)
    assert again['ok'] and again['idempotent'] and again['proposal_commit'] == commit, again
    assert again['generated_paths'] == result['generated_paths']
    assert again['receipt_id'] == result['receipt_id']
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
    assert observed['generated_paths'] == result['generated_paths']
    assert observed['receipt_id'] == result['receipt_id']
    assert not git(root, 'branch', '--list', result['branch'])
    # Evidence validation also uses the immutable Git cut, not a local alias.
    artifact = root / 'docs/synthetic-frozen-capture.json'
    artifact_bytes = artifact.read_bytes()
    external_artifact = tmp_path / 'outside-capture.json'
    external_artifact.write_bytes(artifact_bytes)
    try:
        artifact.unlink()
        artifact.symlink_to(external_artifact)
        immutable = run_git_workflow(root, load_config(root), 'reconcile_contribution',
                                    {'request': request, 'pr': 7}, dry_run=False)
        assert immutable['ok'] and immutable['canonical_body_adopted'], immutable
        assert artifact.is_symlink() and external_artifact.read_bytes() == artifact_bytes
    finally:
        artifact.unlink()
        artifact.write_bytes(artifact_bytes)
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
               and value.get('generated_paths') == result['generated_paths']
               and value.get('receipt_id') == result['receipt_id']
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


@pytest.mark.parametrize('unselected_tail,inherited_event', [(False, False), (True, False), (False, True)])
def test_new_annotations_keep_historical_consumption_across_two_real_preparations(tmp_path, unselected_tail, inherited_event):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True,
        captured=True, effects=True, historical_consumer=True, unselected_tail=unselected_tail,
        inherited_event=inherited_event, qualified_context=inherited_event)
    original = json.loads(records.read_text())
    prior_consumption = [b for b in original['bindings'] if b.get('target_record') == 'remainder']
    assert len(prior_consumption) == 2
    prepared = []
    for number in (1, 2):
        if number == 2:
            before = action.read_text()
            text = before + '\nA second independently reviewed fictional observation.\n'
            request = {**request, 'effect_key': 'synthetic-contract-body-two',
                       'run_ref': {**request['run_ref'], 'run_id': 'two'},
                       'files': [{**request['files'][0], 'base_commit': git(root, 'rev-parse', 'HEAD'),
                                  'base_sha256': digest(before), 'sha256': digest(text), 'text': text}]}
        result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                                  {'request': request, 'review': review(request)}, dry_run=False)
        print(json.dumps({'preparation': number, **result}, sort_keys=True))
        assert result['ok'] and result['status'] == 'prepared', result
        assert all(g['exit_code'] == 0 for g in result['gate_receipts'])
        generated = json.loads(git(root, 'show', result['proposal_commit'] + ':' + records.relative_to(root).as_posix()))
        assert [b for b in generated['bindings'] if b.get('target_record') == 'remainder'] == prior_consumption
        assert generated['base_documents_sha256'] == original['base_documents_sha256']
        if inherited_event:
            assert generated['canonical_log_annotation_context'] == original['canonical_log_annotation_context']
            contexts = [b for b in generated['bindings'] if b['edge_sha256'] ==
                        original['canonical_log_annotation_context']['bindings'][0]['edge_sha256']]
            assert contexts[0] == next(b for b in original['bindings'] if b['consumer_record'] == 'preserved-note')
            assert len(contexts) == 2 + number
            assert all(b['prerequisite_document_sha256'] == contexts[0]['prerequisite_document_sha256']
                       and 'evidence' not in b for b in contexts)
        annotations = [r for d in generated['documents'] if d['path'] == log.relative_to(root).as_posix()
                       for r in d['records'] if r['id'].startswith('contribution-')]
        assert len(annotations) == number
        assert len({r['heading'] for r in annotations}) == number
        assert annotations[0]['leading_blank_lines'] == (2 if unselected_tail else 0)
        again = run_git_workflow(root, load_config(root), 'prepare_contribution',
                                 {'request': request, 'review': review(request)}, dry_run=False)
        assert again['ok'] and again['idempotent'] and again['receipt_id'] == result['receipt_id']
        assert again['proposal_commit'] == result['proposal_commit']
        prepared.append(result)
        # Actual local Git adoption; this test makes no provider/served claim.
        git(root, 'merge', '--ff-only', result['proposal_commit'])
    assert prepared[0]['receipt_id'] != prepared[1]['receipt_id']
    assert len([r for r in json.loads(records.read_text())['artifacts']
                if r.get('field') == 'action_state_history']) == 2


def test_new_annotation_does_not_infer_inherited_event_qualification(tmp_path):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True,
        captured=True, effects=True, inherited_event=True)
    before = {p: p.read_bytes() for p in (action, log, records)}
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    assert result['ok'] and result['status'] == 'prepared', result
    generated = json.loads(git(root, 'show', result['proposal_commit'] + ':' + records.relative_to(root).as_posix()))
    event_bindings = [b for b in generated['bindings'] if b.get('consumer_record', '').startswith('contribution-')]
    assert not event_bindings
    candidate = project_memory_at_commit(result['proposal_commit'], authored_graph, root=root)
    base = project_memory_at_commit(load_config(root).audit['freshness_base'], authored_graph, root=root)
    artifacts = {key: p.read_bytes() for key, p in artifact_paths(root, generated).items()}
    projected, _, _, _ = project_records(candidate, base,
        {action.relative_to(root).as_posix(), log.relative_to(root).as_posix()}, generated, artifact_inputs=artifacts)
    assert any(e['type'] == 'impact' and e.get('field') == 'consolidated_into'
               and e['target'].endswith('::record:contribution-' + port.digest(request)) for e in projected['edges'])
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'rev-parse', 'HEAD') == request['files'][0]['base_commit']


def test_new_annotation_does_not_requalify_changed_consumer_occurrence(tmp_path):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True,
        captured=True, effects=True, historical_consumer=True, changed_consumer=True)
    before = {p: p.read_bytes() for p in (action, log, records)}
    refs = git(root, 'for-each-ref', '--format=%(refname) %(objectname)')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    assert not result['ok'] and result['error'] == (
        'record_support_c3_required:contract:record contract has stale or unmatched consumption bindings'), result
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'for-each-ref', '--format=%(refname) %(objectname)') == refs


def test_retained_legacy_annotation_reconstructs_without_new_records(tmp_path, monkeypatch):
    from functools import partial
    from wiki_core.action_transition import append_contribution_log

    root, action, log, records, request = fullmap_consumer(tmp_path, support=True,
                                                          captured=True, effects=True)
    original = json.loads(records.read_text())
    # Produce the prior exact canonical format using the retained real writer.
    # Only the format selection is historical; all preparation gates still run.
    with monkeypatch.context() as compatibility:
        compatibility.setattr(port, 'append_contribution_log', partial(append_contribution_log, legacy=True))
        result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                                  {'request': request, 'review': review(request)}, dry_run=False)
    assert result['ok'] and result['status'] == 'prepared', result
    generated = json.loads(git(root, 'show', result['proposal_commit'] + ':' + records.relative_to(root).as_posix()))
    assert generated['artifacts'] == original['artifacts']
    assert len(generated['documents'][0]['records']) == len(original['documents'][0]['records'])
    recovered = run_git_workflow(root, load_config(root), 'prepare_contribution',
                                 {'request': request, 'review': review(request)}, dry_run=False)
    assert recovered['ok'] and recovered['idempotent'], recovered
    assert recovered['proposal_commit'] == result['proposal_commit']
    assert recovered['receipt_id'] == result['receipt_id']


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
        support_path(tmp_path, parent, require_worktree=True)
    if case in {'symlink', 'executable'}:
        assert support_path(tmp_path, parent) == ref


@pytest.mark.parametrize('mutation', ['wrong_target', 'consumer_context'])
def test_effect_marker_cannot_author_other_targets_or_changed_context(tmp_path, mutation):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True,
        captured=True, effects=True, effect_consumer=mutation == 'consumer_context')
    if mutation == 'wrong_target':
        contract = json.loads(records.read_text())
        graph = authored_graph(root, load_config(root))
        edge, = [e for e in graph['edges'] if e.get('source') == 'memories/example/index.md'
                 and e.get('target') == 'memories/actions/contract-example.md']
        contract['bindings'][0].update(edge_sha256=edge_digest(edge),
                                       prerequisite_document_sha256=digest(action.read_text()))
        records.write_text(json.dumps(contract, indent=2) + '\n')
        git(root, 'add', str(records))
        git(root, 'commit', '-qm', 'Synthetic misplaced effect qualification')
    before = {p: p.read_bytes() for p in (action, log, records)}
    refs = git(root, 'for-each-ref', '--format=%(refname) %(objectname)')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    expected = 'record_support_effect_requires_configured_log' if mutation == 'wrong_target' else 'record_support_effect_consumer_context_changed'
    assert not result['ok'] and result['error'] == expected, result
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'for-each-ref', '--format=%(refname) %(objectname)') == refs


def test_log_effect_qualification_does_not_anticipate_utc_producer_updates(tmp_path):
    root, action, log, records, request = fullmap_consumer(tmp_path, support=True,
        captured=True, effects=True, prior_day=True)
    before = {p: p.read_bytes() for p in (action, log, records)}
    refs = git(root, 'for-each-ref', '--format=%(refname) %(objectname)')
    result = run_git_workflow(root, load_config(root), 'prepare_contribution',
                              {'request': request, 'review': review(request)}, dry_run=False)
    assert not result['ok'] and result['error'].startswith('proposal_gate_failed:'), result
    failed = result['gate_receipts'][-1]
    assert failed['exit_code'] != 0 and failed['argv'][1] == 'scripts/wiki_operational_pass.py', result
    assert {p: p.read_bytes() for p in before} == before
    assert git(root, 'for-each-ref', '--format=%(refname) %(objectname)') == refs
