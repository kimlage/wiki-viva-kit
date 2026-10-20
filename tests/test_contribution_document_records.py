"""Real public kit gates for a contribution under an exact record contract.

Only synthetic local Git/CLI data; no provider, model, account or GitHub call.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from wiki_core.config import load_config
from wiki_core.document_records import digest, sections
from wiki_core.freshness_impact import authored_graph
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.web.git_workflows import run_git_workflow
from test_action_contribution import review


SOURCE = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()


def command(root, *args):
    result = subprocess.run(args, cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, (args, result.stdout[-5000:], result.stderr[-2000:])
    return result.stdout


def fullmap_consumer(tmp_path):
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
    today = dt.date.today().isoformat()
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
    records = root / 'docs/contribution-records.json'
    records.write_text(json.dumps(contract, indent=2) + '\n')
    config_file = root / 'wiki.config.yaml'
    config = yaml.safe_load(config_file.read_text())
    config['repo_id'] = 'synthetic-contract-consumer'
    config.setdefault('audit', {}).update(freshness_scope='impact', freshness_base=base,
                                         freshness_records='docs/contribution-records.json')
    config_file.write_text(yaml.safe_dump(config, sort_keys=False))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'Bind complete exact documentary contract')
    # Prove a healthy actual baseline before the contribution introduces drift.
    command(root, sys.executable, 'scripts/wiki_audit.py', '--check')
    command(root, sys.executable, 'scripts/wiki_input_stage.py', '--check')
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
